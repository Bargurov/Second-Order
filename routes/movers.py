"""Route handlers for /market-movers and /movers/* endpoints."""

from datetime import datetime, timedelta
import os
import re

from fastapi import APIRouter, HTTPException, Query

from mover_card_normalizer import (
    apply_diversity_guardrails,
    compute_mover_meta,
    enrich_mover_cards,
    is_high_conviction_persistent,
)
from overlay_sanitize import sanitize_mover_card
import movers_cache
import api as _api
import headline_registry as _hr
from news_sources import _dedup_key as _hr_dedup_key

# Windows that receive the diversity guardrail pass.  ``persistent``
# is intentionally excluded — a follow-through surface orders by
# persistence signals the guardrail would scramble.
_GUARDRAIL_WINDOWS: frozenset[str] = frozenset({"today", "weekly", "market"})

# Over-fetch ceiling for the persistent surface.  The cache stores
# the unlimited payload, so reading 100 raw cards and trimming to
# ``limit`` after the high-conviction filter keeps the surface honest
# without starving it when most rows fail the gate.
_PERSISTENT_OVERFETCH: int = 100

router = APIRouter()

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_DEFAULT_BACKFILL_PROVIDER = "openai"
_DEFAULT_BACKFILL_MODEL = "gpt-4o-mini"
_DEFAULT_MAX_BACKFILL_LLM_CALLS = 1
_LLM_PROVIDERS = {"anthropic", "openai"}


def _env_text(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = _env_text(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _env_bool(name: str, default: bool) -> bool:
    raw = _env_text(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _analysis_provider() -> str:
    provider = (_env_text("ANALYSIS_PROVIDER") or "anthropic").lower()
    return provider if provider in _LLM_PROVIDERS else "anthropic"


def _backfill_provider() -> str:
    provider = (_env_text("BACKFILL_PROVIDER") or _DEFAULT_BACKFILL_PROVIDER).lower()
    return provider if provider in _LLM_PROVIDERS else _DEFAULT_BACKFILL_PROVIDER


def _backfill_model(provider: str) -> str:
    configured = (
        _env_text("BACKFILL_MODEL")
        or _env_text("ANTHROPIC_BACKFILL_MODEL")
        or _env_text("CLAUDE_BACKFILL_MODEL")
    )
    if configured:
        return configured
    return _DEFAULT_BACKFILL_MODEL if provider == "openai" else "claude-haiku-4-5-20251001"


def _backfill_model_key(provider: str, model: str) -> str:
    return f"{provider}:{model}"


def _max_backfill_llm_calls() -> int:
    return _env_int(
        "MAX_BACKFILL_LLM_CALLS",
        _env_int(
            "MOVERS_BACKFILL_MAX_LLM_CALLS",
            _DEFAULT_MAX_BACKFILL_LLM_CALLS,
            minimum=0,
            maximum=20,
        ),
        minimum=0,
        maximum=20,
    )


def _paid_analysis_enabled() -> bool:
    """Server-side master switch for paid LLM analysis paths.

    When ``ENABLE_PAID_ANALYSIS`` is unset, false, or otherwise falsy,
    every paid endpoint must short-circuit BEFORE any LLM /
    market_check / persistence work — even when the request carries
    ``confirm_paid=true`` and a per-call budget within
    ``MAX_BACKFILL_LLM_CALLS``.  The two URL-level guards
    (``confirm_paid`` and ``max_llm_calls``) protect against accidental
    UI clicks; this env switch is the operator-level kill-switch that
    a deployment can flip without touching code.

    Default false — the safe state for an unconfigured environment is
    "no spend" so a fresh checkout cannot accidentally call the LLM
    even with the right query params.
    """
    return _env_bool("ENABLE_PAID_ANALYSIS", False)


def _backfill_dry_run_default() -> bool:
    return _env_bool(
        "BACKFILL_DRY_RUN_DEFAULT",
        _env_bool("MOVERS_BACKFILL_DRY_RUN", True),
    )


def load_ui_slices_for_event_context(limit: int = 100) -> dict[str, list[dict]]:
    """Return UI-ready mover cards per window, for the mover_context block.

    Reuses the same pipeline the HTTP endpoints use
    (``sanitize_mover_card`` → ``enrich_mover_cards``) so the cards
    the detail route sees match what the mover endpoints surface.
    Each underlying slice is already TTL-cached — reading is cheap
    and never triggers a new market fetch.  Individual slice
    failures degrade to ``[]`` rather than raising so one flaky
    window can't block the detail response.
    """
    out: dict[str, list[dict]] = {
        "today": [], "market": [], "weekly": [], "persistent": [],
    }

    def _enrich(raw, *, window: str) -> list[dict]:
        if not isinstance(raw, list):
            return []
        scrubbed = [sanitize_mover_card(c) for c in raw]
        return enrich_mover_cards(scrubbed, window=window)

    try:
        out["today"] = _enrich(
            _api.movers_today(limit=limit), window="today",
        )
    except Exception:
        pass
    try:
        out["market"] = _enrich(
            movers_cache.get_slice(
                "market_movers", limit=limit,
                ttl_seconds=_api._MARKET_MOVERS_TTL,
            ),
            window="market",
        )
    except Exception:
        pass
    try:
        out["weekly"] = _enrich(
            movers_cache.get_slice(
                "weekly", limit=limit, ttl_seconds=_api._WEEKLY_MOVERS_TTL,
            ),
            window="weekly",
        )
    except Exception:
        pass
    try:
        # Mirror the route-level high-conviction gate so the detail
        # block never advertises a card the /movers/persistent surface
        # would itself reject.
        raw_persistent = movers_cache.get_slice(
            "persistent", limit=_PERSISTENT_OVERFETCH,
            ttl_seconds=_api._PERSISTENT_MOVERS_TTL,
        )
        if isinstance(raw_persistent, list):
            raw_persistent = [
                c for c in raw_persistent if is_high_conviction_persistent(c)
            ][:limit]
        out["persistent"] = _enrich(raw_persistent, window="persistent")
    except Exception:
        pass
    return out


def _sanitize_movers(cards, *, window: str):
    """Normalise a raw mover list into the UI-ready card shape.

    Returns the task-pinned response envelope:

        {"items": [...], "meta": {surfaced_count, unique_clusters,
                                  unique_families}}

    Pipeline per endpoint:
      1. ``sanitize_mover_card`` — attach ``data_quality`` markers and
         scrub NaN/inf.
      2. ``enrich_mover_cards`` — merge UI-ready fields and run the
         window-aware quality gate (filter / dedup / demote).
      3. ``apply_diversity_guardrails`` — re-rank on today/weekly/market
         so one mechanism family can't dominate the surface.
      4. ``compute_mover_meta`` — emit the response meta block.
      5. ``_sanitize_floats`` — belt-and-braces JSON safety on both
         the items list and the meta block.
    """
    return _sanitize_movers_with_meta(cards, window=window)


def _has_diagnostic_content(diagnostics: dict | None) -> bool:
    if not isinstance(diagnostics, dict):
        return False
    if diagnostics.get("events_scanned") or diagnostics.get("candidate_cards"):
        return True
    coverage = diagnostics.get("headline_coverage") or {}
    if isinstance(coverage, dict) and (
        coverage.get("clusters_cached") or coverage.get("total_headlines")
    ):
        return True
    rejected = diagnostics.get("rejections") or {}
    return isinstance(rejected, dict) and any(rejected.values())


def _sanitize_movers_with_meta(cards, *, window: str, diagnostics: dict | None = None):
    if not isinstance(cards, list):
        safe = _api._sanitize_floats(cards)
        items = safe if isinstance(safe, list) else []
        meta = compute_mover_meta([])
        if not items and _has_diagnostic_content(diagnostics):
            meta["diagnostics"] = diagnostics
        return {"items": items, "meta": _api._sanitize_floats(meta)}
    scrubbed = [sanitize_mover_card(c) for c in cards]
    enriched = enrich_mover_cards(scrubbed, window=window)
    if window in _GUARDRAIL_WINDOWS:
        enriched = apply_diversity_guardrails(enriched)
    items = _api._sanitize_floats(enriched)
    meta = _api._sanitize_floats(compute_mover_meta(items))
    if not items and _has_diagnostic_content(diagnostics):
        meta["diagnostics"] = _api._sanitize_floats(diagnostics)
    return {"items": items, "meta": meta}


def _recent_events_for_diagnostics() -> list[dict]:
    try:
        from db import load_recent_events
        return load_recent_events(500)
    except Exception:
        return []


def _cached_news_payload() -> tuple[dict | None, str]:
    """Read the current news payload from hot/SQLite caches without fetching."""
    payload = None
    source = "none"
    try:
        hot = getattr(_api, "_news_cache", {}).get("data")
        if isinstance(hot, dict) and _api._is_valid_news_payload(hot):
            payload = hot
            source = "memory"
    except Exception:
        payload = None

    if payload is None:
        try:
            from db import load_news_cache
            db_payload = load_news_cache(max_age_seconds=86400)
            if isinstance(db_payload, dict) and _api._is_valid_news_payload(db_payload):
                payload = db_payload
                source = "sqlite"
        except Exception:
            payload = None

    return (payload if isinstance(payload, dict) else None, source)


def _cached_news_probe() -> dict:
    """Read headline coverage from existing caches without fetching feeds."""
    payload, source = _cached_news_payload()
    if not isinstance(payload, dict):
        return {
            "source": source,
            "clusters_cached": 0,
            "total_headlines": 0,
            "refresh_status": None,
            "freshness": None,
            "last_successful_refresh": None,
        }

    clusters = payload.get("clusters") or []
    meta = payload.get("refresh_meta") or {}
    return {
        "source": source,
        "clusters_cached": len(clusters) if isinstance(clusters, list) else 0,
        "total_headlines": payload.get("total_headlines", 0) or 0,
        "refresh_status": meta.get("status"),
        "freshness": meta.get("freshness"),
        "last_successful_refresh": meta.get("last_successful_refresh"),
    }


def _coverage_status(diagnostics: dict, news_probe: dict) -> str:
    rejections = diagnostics.get("rejections") or {}
    has_fresh_headlines = bool(
        news_probe.get("clusters_cached") or news_probe.get("total_headlines")
    )
    # Today accepts return_1d as a fallback (matches
    # ``_today_window_qualify``).  For coverage attribution, count
    # raw return_1d as evidence of "market-checked candidates" so the
    # status doesn't read as if no provider data ever arrived.
    window = diagnostics.get("window") or ""
    accept_return_1d = window == "today"
    has_market_checked_candidates = bool(
        diagnostics.get("window_events_with_raw_return_5d")
    )
    if accept_return_1d:
        has_market_checked_candidates = (
            has_market_checked_candidates
            or bool(diagnostics.get("window_events_with_raw_return_1d"))
        )
    if diagnostics.get("eligible_events"):
        return "eligible_mover_candidates_found"
    if has_market_checked_candidates:
        return "filters_rejected_market_checked_candidates"
    if diagnostics.get("window_events_with_raw_tickers"):
        # Today-window pages here only when neither return_5d nor
        # return_1d is present — ``no usable return`` is the honest
        # description; other slices still report missing ``return_5d``.
        return (
            "analyzed_events_missing_usable_return" if accept_return_1d
            else "analyzed_events_missing_return_5d"
        )
    if diagnostics.get("window_events"):
        if rejections:
            only_filter_rejections = all(
                key in {
                    "mock_event", "low_signal", "insufficient_evidence",
                    "irrelevant_headline", "duplicate_headline",
                }
                for key in rejections
            )
            if only_filter_rejections:
                return "filters_rejected_candidates_before_market_check"
        return "analyzed_events_missing_market_tickers"
    if has_fresh_headlines:
        return "fresh_headlines_without_analyzed_market_events"
    return "no_headline_or_event_candidates"


def _coverage_summary(status: str, diagnostics: dict, news_probe: dict) -> str | None:
    clusters = news_probe.get("clusters_cached") or 0
    total = news_probe.get("total_headlines") or 0
    if status == "fresh_headlines_without_analyzed_market_events":
        return (
            "Fresh headline clusters exist, but no saved analyzed events in "
            "this mover window have market_tickers/return_5d yet."
        )
    if status == "analyzed_events_missing_market_tickers":
        return (
            "Saved analyzed events exist in this mover window, but none carry "
            "market_tickers for movers to score."
        )
    if status == "analyzed_events_missing_return_5d":
        return (
            "Saved analyzed events have market_tickers, but no usable return_5d "
            "values after ticker scrubbing."
        )
    if status == "analyzed_events_missing_usable_return":
        return (
            "Saved analyzed events have market_tickers, but neither return_5d "
            "nor return_1d is populated — backfill / market_check has not yet "
            "produced provider returns for them."
        )
    if status in (
        "filters_rejected_market_checked_candidates",
        "filters_rejected_candidates_before_market_check",
    ):
        return "Candidate events existed, but mover quality filters rejected them."
    if clusters or total:
        return diagnostics.get("summary")
    return None


def _attach_headline_coverage(diagnostics: dict | None) -> dict | None:
    if not isinstance(diagnostics, dict):
        return diagnostics
    news_probe = _cached_news_probe()
    status = _coverage_status(diagnostics, news_probe)
    window = diagnostics.get("window") or ""
    market_check_source = (
        "Saved analyzed events must carry market_tickers with return_5d "
        "(or return_1d as a fallback for events younger than the 5-day "
        "window); /movers/today reads those persisted event-linked moves."
        if window == "today" else
        "Saved analyzed events must carry market_tickers with return_5d; "
        "mover endpoints only read those persisted event-linked moves."
    )
    diagnostics["headline_coverage"] = {
        **news_probe,
        "status": status,
        "analysis_path": {
            "analyze_endpoint": "POST /analyze",
            "stream_endpoint": "POST /analyze/stream",
            "backfill_endpoint": "POST /movers/backfill-recent",
            "market_check_source": market_check_source,
        },
    }
    summary = _coverage_summary(status, diagnostics, news_probe)
    if summary:
        diagnostics["summary"] = summary
    return diagnostics


def _time_window_diagnostics(slice_name: str) -> dict | None:
    try:
        filter_low_signal = slice_name in ("today", "weekly")
        diagnostics = movers_cache.diagnose_time_slice(
            slice_name,
            _recent_events_for_diagnostics(),
            filter_low_signal=filter_low_signal,
            mover_threshold=(
                _api._MOVER_THRESHOLD if slice_name == "market_movers" else None
            ),
        )
        return _attach_headline_coverage(diagnostics)
    except Exception:
        return None


def _llm_available(provider: str) -> bool:
    key_name = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
    key = os.environ.get(key_name, "").strip()
    return bool(
        key
        and key.lower()
        not in {
            "your_api_key_here",
            "your_anthropic_api_key_here",
            "your_openai_api_key_here",
            "placeholder",
            "changeme",
        }
    )


def _sort_news_clusters(clusters: list[dict]) -> list[dict]:
    return sorted(
        [c for c in clusters if isinstance(c, dict)],
        key=lambda c: (
            c.get("source_count", 0) or 0,
            c.get("published_at", "") or "",
            c.get("id", 0) or 0,
        ),
        reverse=True,
    )


def _cluster_headline(cluster: dict) -> str:
    try:
        return _api.normalize_headline(cluster.get("headline") or "").strip()
    except Exception:
        return str(cluster.get("headline") or "").strip()


def _cluster_event_date(cluster: dict) -> str:
    published = str(cluster.get("published_at") or "")
    if len(published) >= 10:
        candidate = published[:10]
        try:
            datetime.fromisoformat(candidate)
            return candidate
        except ValueError:
            pass
    return datetime.now().strftime("%Y-%m-%d")


def _cluster_event_context(cluster: dict) -> str:
    parts: list[str] = []
    summary = str(cluster.get("summary") or "").strip()
    if summary:
        parts.append(f"Cluster summary: {summary}")
    sources = cluster.get("sources") or []
    if isinstance(sources, list):
        names = [
            str(s.get("name") or "").strip()
            for s in sources[:6]
            if isinstance(s, dict) and s.get("name")
        ]
        if names:
            parts.append("Sources: " + ", ".join(names))
    evidence = cluster.get("evidence") or []
    if isinstance(evidence, list):
        snippets: list[str] = []
        for row in evidence[:4]:
            if isinstance(row, dict):
                text = row.get("title") or row.get("headline") or row.get("text")
            else:
                text = row
            text = str(text or "").strip()
            if text:
                snippets.append(text)
        if snippets:
            parts.append("Cluster evidence:\n" + "\n".join(f"- {s}" for s in snippets))
    return "\n\n".join(parts)[:5000]


def _find_recent_saved_event(headline: str, event_date: str, model: str) -> dict | None:
    cached = _api.find_cached_analysis(
        headline,
        event_date=event_date,
        model=model,
    ) or _api.find_cached_analysis(headline, event_date=event_date)
    if cached is not None:
        return cached
    try:
        normalized = _api.normalize_headline(headline)
    except Exception:
        normalized = headline
    for event in _recent_events_for_diagnostics():
        try:
            candidate = _api.normalize_headline(event.get("headline") or "")
        except Exception:
            candidate = event.get("headline") or ""
        if candidate == normalized:
            return event
    return None


def _ticker_symbols(values) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def _add(value) -> None:
        if isinstance(value, dict):
            value = value.get("symbol") or value.get("ticker") or value.get("asset")
        raw = str(value or "").strip()
        sym = raw.upper()
        if raw != sym or not _TICKER_RE.match(sym):
            return
        if sym not in seen:
            seen.add(sym)
            out.append(sym)

    for item in values or []:
        _add(item)
    return out


def _fallback_ticker_symbols_from_analysis(analysis: dict) -> list[str]:
    """Extract candidate tickers from the analysis when the cleaned
    beneficiary / loser lists are empty.

    Walks ``primary_assets`` → ``secondary_assets`` → ``assets_to_watch``
    in that order, skipping ``hedge_or_signal_assets`` so VIX / DXY /
    inverse-ETF symbols don't get mis-classified as beneficiaries.  The
    resulting list is filtered through ``_ticker_symbols`` so foreign
    suffixes and non-public symbols are dropped before they reach
    ``market_check``.
    """
    if not isinstance(analysis, dict):
        return []
    candidates: list = []
    for bucket_key in ("primary_assets", "secondary_assets"):
        bucket = analysis.get(bucket_key)
        if isinstance(bucket, list):
            candidates.extend(bucket)
    atw = analysis.get("assets_to_watch")
    if isinstance(atw, list):
        candidates.extend(atw)
    return _ticker_symbols(candidates)


_ASSET_TERM_RE = re.compile(
    r"\b(?:NYSE|NASDAQ|AMEX|ETF|Inc\.?|Corp\.?|Ltd\.?|PLC|SA|AG|Holdings|"
    r"shares|stock|ticker|earnings|dividend|buyback|IPO|listing|index|bonds?|"
    r"yield|spread|treasur(?:y|ies))\b",
    re.IGNORECASE,
)
_ASSET_TICKER_RE = re.compile(r"\$[A-Z]{2,5}\b|\([A-Z]{2,5}(?:[.\-][A-Z]{1,3})?\)")


def _cluster_has_asset_terms(cluster: dict) -> bool:
    """True when the cluster headline names a company / asset class
    with enough specificity that a downstream LLM call is likely to
    surface a public ticker.

    Used as a tie-breaker for cluster ordering — clusters at the same
    ``source_count`` are preferred when they contain explicit ticker
    syntax (``$AAPL``, ``(AAPL)``) or named-entity terms (Inc., Corp.,
    Holdings, ETF, etc.).
    """
    headline = str(cluster.get("headline") or "")
    if not headline:
        return False
    if _ASSET_TICKER_RE.search(headline):
        return True
    return bool(_ASSET_TERM_RE.search(headline))


# Zero-cost preview ranking
# ---------------------------------------------------------------------------
# /movers/backfill-preview ranks candidate clusters using metadata that
# is already in the cached news payload (no LLM, no market_check, no
# yfinance).  Weights are intentionally separated so the operator can
# read each component on the per-item ``rank_factors`` block; tuning
# them later is a one-place edit.
_RANK_W_SOURCE_COUNT_PER     = 1.0   # per publisher, clamped to _RANK_SOURCE_COUNT_CAP
_RANK_SOURCE_COUNT_CAP       = 8     # diminishing returns past this
_RANK_W_HIGH_TIER_PER        = 1.5   # per high-tier publisher in `sources`
_RANK_W_ASSET_TERMS          = 1.5   # explicit ticker / company-form mention
_RANK_W_MACRO_POLICY         = 3.0   # central bank, CPI / payrolls, rate decision
_RANK_W_GEOPOLITICAL         = 2.5   # sanctions / tariffs / military escalation
_RANK_W_COMMODITY_POLICY     = 2.5   # OPEC, crude / LNG output, rare-earth quotas
_RANK_W_CORPORATE_ACTION     = 1.0   # M&A, buyback, IPO, guidance reset
_RANK_W_GENERIC_NOISE        = -3.0  # market-wrap roundups w/ no specific event

_MACRO_POLICY_RE = re.compile(
    r"\b("
    r"federal\s+reserve|fed(?:eral)?\b|fomc|"
    r"ecb|boj|boe|pboc|snb|rba|rbnz|bank\s+of\s+(?:england|japan|canada|korea)|"
    r"central\s+bank|monetary\s+policy|rate\s+(?:cut|hike|decision|hold)s?|"
    r"interest\s+rate(?:s)?|cpi|ppi|pce|nonfarm|payrolls|jobs\s+report|"
    r"inflation|unemployment|gdp|recession|stimulus|quantitative"
    r")\b",
    re.IGNORECASE,
)
_GEOPOLITICAL_RE = re.compile(
    r"\b("
    r"sanction(?:s|ed|ing)?|embargo(?:es|ed)?|tariff(?:s)?|export\s+control|"
    r"missile|airstrike|invasion|escalat(?:e|es|ed|ion)|retaliat(?:e|es|ed|ion)|"
    r"strait\s+of\s+hormuz|red\s+sea|suez|blockade|"
    r"nato|kremlin|white\s+house|pentagon|brussels|"
    r"ceasefire|truce|treaty|annex(?:ed|ation)?"
    r")\b",
    re.IGNORECASE,
)
_COMMODITY_POLICY_RE = re.compile(
    r"\b("
    r"opec(?:\+|plus)?|crude(?:\s+oil)?|brent|wti|natural\s+gas|lng|"
    r"oil\s+(?:output|production|export|price|embargo|sanction)|"
    r"rare\s+earth(?:s)?|lithium|cobalt|copper|nickel|uranium|"
    r"semiconductor(?:s)?|chip\s+(?:export|import|ban)|wafer|foundry|"
    r"wheat|grain|fertili[sz]er"
    r")\b",
    re.IGNORECASE,
)
_CORPORATE_ACTION_RE = re.compile(
    r"\b("
    r"merger|acquisition|acquires?|takeover|buyback|repurchase|"
    r"ipo\b|listing|spin[\s\-]?off|"
    r"earnings|guidance|profit\s+warning|"
    r"dividend\s+(?:cut|raise|hike)|"
    r"layoffs?|restructur(?:e|ing)"
    r")\b",
    re.IGNORECASE,
)
# Wire-style market-wrap headlines: high source_count, low informational
# value.  Penalty pushes them below specific-event headlines even when
# many publishers cover the daily roundup.
_GENERIC_FINANCE_NOISE_RE = re.compile(
    r"\b("
    r"market\s+wrap|markets?\s+(?:close|open)|"
    r"stocks?\s+(?:open|close|edge|ease|rise|fall|slip|gain|drop)|"
    r"shares?\s+(?:open|close|edge|ease|rise|fall|slip|gain|drop)|"
    r"wall\s+street\s+(?:close|open|wrap|recap|edges?)|"
    r"asia\s+(?:close|opens?)|europe\s+(?:close|opens?)|"
    r"yields?\s+(?:tick|edge|drift|inch)|"
    r"recap\b|roundup\b|wrap[\s\-]?up\b|"
    r"light\s+trading|quiet\s+trading|range[\s\-]bound"
    r")\b",
    re.IGNORECASE,
)


def _cluster_high_tier_source_count(cluster: dict) -> int:
    """Number of high-tier publishers in ``cluster["sources"]``.

    Uses ``news_fetch.source_tier`` (re-exported from ``news_sources``)
    so the tier list stays in one place.  Missing or malformed
    ``sources`` returns 0 — the scorer treats unknown providers as low
    tier rather than raising on a feed that omitted publisher metadata.
    """
    sources = cluster.get("sources") or []
    if not isinstance(sources, list):
        return 0
    from news_sources import source_tier
    count = 0
    for s in sources:
        name = ""
        if isinstance(s, dict):
            name = str(s.get("name") or "").strip()
        elif isinstance(s, str):
            name = s.strip()
        if name and source_tier(name) == "high":
            count += 1
    return count


def _headline_keyword_signals(headline: str) -> dict:
    """Boolean flags for each topical category the scorer cares about.

    All categories run over the same headline text; a single headline
    can light up several flags (an OPEC sanctions headline is both
    ``geopolitical`` and ``commodity_policy``).  ``generic_finance_noise``
    is independent of the boost categories — a noisy wrap could in
    principle name a Fed event, but in practice these flags don't
    co-occur and the boost dominates the penalty.
    """
    text = headline or ""
    return {
        "macro_policy":          bool(_MACRO_POLICY_RE.search(text)),
        "geopolitical":          bool(_GEOPOLITICAL_RE.search(text)),
        "commodity_policy":      bool(_COMMODITY_POLICY_RE.search(text)),
        "corporate_action":      bool(_CORPORATE_ACTION_RE.search(text)),
        "generic_finance_noise": bool(_GENERIC_FINANCE_NOISE_RE.search(text)),
    }


def _score_cluster_for_preview(cluster: dict) -> tuple[float, dict]:
    """Return (rank_score, rank_factors) for one cluster.

    ``rank_factors`` always carries the full keyset (8 keys, defaults
    0/False) so consumers can bind to a stable shape.  Score components
    sum the weighted constants above; the ``factors`` dict carries the
    raw inputs (count of high-tier sources, source_count, asset-term
    boolean, topical booleans) — not the per-component weighted score
    — so a future weight tweak doesn't change the diagnostics shape.
    """
    source_count = int(cluster.get("source_count") or 0)
    high_tier = _cluster_high_tier_source_count(cluster)
    has_asset = _cluster_has_asset_terms(cluster)
    headline = str(cluster.get("headline") or "")
    signals = _headline_keyword_signals(headline)

    score = 0.0
    score += min(source_count, _RANK_SOURCE_COUNT_CAP) * _RANK_W_SOURCE_COUNT_PER
    score += high_tier * _RANK_W_HIGH_TIER_PER
    if has_asset:
        score += _RANK_W_ASSET_TERMS
    if signals["macro_policy"]:
        score += _RANK_W_MACRO_POLICY
    if signals["geopolitical"]:
        score += _RANK_W_GEOPOLITICAL
    if signals["commodity_policy"]:
        score += _RANK_W_COMMODITY_POLICY
    if signals["corporate_action"]:
        score += _RANK_W_CORPORATE_ACTION
    if signals["generic_finance_noise"]:
        score += _RANK_W_GENERIC_NOISE

    factors = {
        "source_count":          source_count,
        "high_tier_sources":     high_tier,
        "has_asset_terms":       has_asset,
        **signals,
    }
    return score, factors


# Display-only labels for backfill preview ──────────────────────────────────
# Additive UI glue.  ``skip_reason`` and ``rank_factors`` stay raw on every
# preview item so existing consumers don't break; the route appends a
# product-facing label/explanation pair so the UI can render without a
# client-side translation table.
_SKIP_REASON_LABELS: dict[str, str] = {
    "low_signal":                  "Low-signal cluster",
    "registry_already_analyzed":   "Already analyzed",
    "registry_expired_low_impact": "Expired (low impact)",
    "already_market_checked":      "Already market-checked",
}

_RANK_TOPIC_LABELS: dict[str, str] = {
    "macro_policy":     "macro",
    "geopolitical":     "geopolitical",
    "commodity_policy": "commodity policy",
    "corporate_action": "corporate action",
}


def _skip_reason_label(skip_reason: str | None) -> str:
    if skip_reason is None:
        return "Eligible for analysis"
    return _SKIP_REASON_LABELS.get(skip_reason, skip_reason)


def _rank_explanation(factors: dict) -> str:
    """One-line, product-facing summary of a ``rank_factors`` block.

    Composes the active topical flags, the source-coverage stats, and
    the asset-mention / market-wrap modifiers — kept short so it fits
    a list row.  ``rank_factors`` is still emitted unchanged so the
    operator UI can drill in when needed.
    """
    parts: list[str] = []
    topics = [
        label for key, label in _RANK_TOPIC_LABELS.items()
        if factors.get(key)
    ]
    if topics:
        joined = " + ".join(topics)
        parts.append(joined[:1].upper() + joined[1:])
    source_count = int(factors.get("source_count") or 0)
    high_tier = int(factors.get("high_tier_sources") or 0)
    if source_count:
        if high_tier:
            parts.append(f"{source_count} sources ({high_tier} high-tier)")
        else:
            parts.append(f"{source_count} sources")
    if factors.get("has_asset_terms"):
        parts.append("asset mention")
    if factors.get("generic_finance_noise"):
        parts.append("market-wrap penalty")
    return " · ".join(parts) or "no signal"


def _has_tickers(tickers) -> bool:
    return isinstance(tickers, list) and any(
        isinstance(t, dict) and t.get("symbol") for t in tickers
    )


def _has_return_5d(tickers) -> bool:
    return isinstance(tickers, list) and any(
        isinstance(t, dict) and t.get("return_5d") is not None for t in tickers
    )


def _has_any_usable_return(tickers) -> bool:
    """True when any ticker carries either ``return_5d`` or ``return_1d``.

    The today-window mover surface (``api.movers_today``) accepts
    ``return_1d`` as a fallback when ``return_5d`` is None — events
    younger than the 5-day window can't have return_5d yet but still
    have a meaningful 1-day reaction.  This helper mirrors that
    contract for the backfill's success metric so a freshly analyzed
    event that produced ``return_1d`` is correctly counted as
    ``with_returns`` rather than reported as ``market_data_unavailable``.
    """
    if not isinstance(tickers, list):
        return False
    for t in tickers:
        if not isinstance(t, dict):
            continue
        if t.get("return_5d") is not None or t.get("return_1d") is not None:
            return True
    return False


def _market_quality(tickers) -> dict:
    safe = tickers if isinstance(tickers, list) else []
    return {
        "with_tickers": _has_tickers(safe),
        # ``with_returns`` reflects "did the run produce usable post-event
        # price data" — return_1d counts because the today-window surface
        # consumes it.  Distinct from the legacy ``_has_return_5d`` helper
        # which is intentionally strict for the persistent gate path.
        "with_returns": _has_any_usable_return(safe),
        "ticker_count": len([t for t in safe if isinstance(t, dict) and t.get("symbol")]),
    }


def _persist_outcome(persisted: bool, with_returns: bool) -> str:
    """Categorical label for a backfill item row.

    Distinguishes ``persisted_with_returns`` (write succeeded AND the
    provider produced usable post-event returns) from
    ``persisted_without_returns`` (write succeeded but the provider call
    came back without ``return_5d``/``return_1d`` for any ticker).
    ``not_persisted`` covers the residual cases — DB write failed, LLM
    unavailable, or skip paths that never reached persistence.
    """
    if persisted and with_returns:
        return "persisted_with_returns"
    if persisted:
        return "persisted_without_returns"
    return "not_persisted"


def _market_status_reason(
    *, persisted: bool, with_tickers: bool, with_returns: bool,
) -> tuple[str, str | None]:
    """Per-item ``status``/``reason`` for market_check / refresh outcomes.

    ``market_data_unavailable`` is reserved for cases where neither the
    provider nor the persist path produced anything usable — i.e., we
    don't even have a row on disk.  When the row WAS saved (with
    tickers but lacking returns), the reason is reported as
    ``persisted_without_returns`` so the operator can distinguish "no
    record at all" from "record on disk awaiting provider returns".
    """
    if with_returns:
        return ("ok", None)
    if persisted and with_tickers:
        return ("degraded", "persisted_without_returns")
    return ("degraded", "market_data_unavailable")


def _refresh_existing_market_event(event: dict) -> dict:
    """Populate market_tickers for a saved event using existing market paths."""
    if not event.get("id"):
        return {"status": "skipped", "reason": "missing_event_id"}

    existing_tickers = event.get("market_tickers") or []
    if existing_tickers:
        from db import update_event_market_refresh

        persisted = {"updated": False}

        def _persist(event_id, tickers, note, last_market_check_at):
            updated = update_event_market_refresh(
                event_id, tickers, note, last_market_check_at,
            )
            persisted["updated"] = bool(updated)
            return updated

        block = _api.refresh_market_for_saved_event(
            event,
            force=True,
            followup_check_fn=_api.followup_check,
            market_check_fn=_api.market_check,
            persist_fn=_persist,
        )
        tickers = block.get("tickers") or []
        quality = _market_quality(tickers)
        status, reason = _market_status_reason(
            persisted=persisted["updated"],
            with_tickers=quality["with_tickers"],
            with_returns=quality["with_returns"],
        )
        return {
            "status": status,
            "reason": reason,
            "outcome": _persist_outcome(persisted["updated"], quality["with_returns"]),
            "persisted": persisted["updated"],
            "market_tickers": tickers,
            "market_note": block.get("note"),
            **quality,
        }

    asset_symbols = _ticker_symbols(event.get("assets_to_watch") or [])
    ben_symbols = _ticker_symbols(event.get("beneficiaries") or [])
    los_symbols = _ticker_symbols(event.get("losers") or [])
    if not ben_symbols and asset_symbols:
        ben_symbols = asset_symbols
    if not ben_symbols and not los_symbols:
        return {"status": "skipped", "reason": "no_asset_candidates"}

    try:
        from asset_selection import classify_and_rank_assets
        selected = classify_and_rank_assets(
            beneficiary_tickers=ben_symbols,
            loser_tickers=los_symbols,
            mechanism_family=event.get("mechanism_family"),
            beneficiaries_text=event.get("beneficiaries") or [],
            losers_text=event.get("losers") or [],
        )
        ben_for_check = selected.get("cleaned_beneficiary_tickers") or []
        los_for_check = selected.get("cleaned_loser_tickers") or []
    except Exception:
        _api._log.warning(
            "movers backfill asset_selection failed; using raw symbols",
            exc_info=True,
        )
        ben_for_check = ben_symbols
        los_for_check = los_symbols

    if not ben_for_check and not los_for_check:
        return {"status": "skipped", "reason": "no_market_eligible_assets"}

    mkt = _api.market_check(
        ben_for_check,
        los_for_check,
        event_date=event.get("event_date"),
    )
    tickers = mkt.get("tickers") or []
    from db import update_event_market_refresh
    updated = update_event_market_refresh(
        int(event["id"]),
        tickers,
        mkt.get("note") or "",
        datetime.now().isoformat(timespec="seconds"),
    )
    quality = _market_quality(tickers)
    status, reason = _market_status_reason(
        persisted=bool(updated),
        with_tickers=quality["with_tickers"],
        with_returns=quality["with_returns"],
    )
    return {
        "status": status,
        "reason": reason,
        "outcome": _persist_outcome(bool(updated), quality["with_returns"]),
        "persisted": bool(updated),
        "market_tickers": tickers,
        "market_note": mkt.get("note"),
        **quality,
    }


def _fresh_analysis_market_event(
    headline: str,
    *,
    event_context: str,
    event_date: str,
    provider: str,
    model: str,
    model_key: str,
    existing_event: dict | None = None,
) -> dict:
    """Run the normal analysis composers, then market-check and persist/update."""
    from analyze_event import AnalyzeEventInput
    from routes.analyze import (
        _enrich_macro_context_with_country,
        _run_post_market_overlays,
        _run_pre_market_overlays,
    )

    stage = _api.classify_stage(headline)
    persistence = _api.classify_persistence(headline)

    macro_context = ""
    try:
        macro_context = _api.build_macro_context_for_prompt()
    except Exception:
        _api._log.warning(
            "macro context pre-fetch failed (movers backfill)", exc_info=True,
        )
    macro_context = _enrich_macro_context_with_country(macro_context, headline)

    analysis = _api.analyze_event(AnalyzeEventInput(
        headline=headline,
        stage=stage,
        persistence=persistence,
        event_context=event_context,
        macro_context=macro_context,
        model=model,
        provider=provider,
    ))
    if _api._is_mock_analysis(analysis):
        return {
            "status": "degraded",
            "reason": "llm_unavailable_or_mock_analysis",
            "outcome": "not_persisted",
            "analyzed": False,
            "persisted": False,
            "market_tickers": [],
            **_market_quality([]),
        }

    analysis["if_persists"] = _api._normalize_if_persists(
        analysis.get("if_persists"),
    )
    analysis["currency_channel"] = _api._normalize_currency_channel(
        analysis.get("currency_channel"),
    )
    mech_text = (
        f"{analysis.get('what_changed', '')} "
        f"{analysis.get('mechanism_summary', '')}"
    )
    rates_for_overlays, stress_for_overlays = _run_pre_market_overlays(
        analysis, headline, mech_text, stage, persistence,
    )

    raw_ben = analysis.get("beneficiary_tickers") or []
    raw_los = analysis.get("loser_tickers") or []
    raw_atw = analysis.get("assets_to_watch") or []

    try:
        from asset_selection import classify_and_rank_assets
        analysis["asset_selection"] = classify_and_rank_assets(
            beneficiary_tickers=raw_ben,
            loser_tickers=raw_los,
            mechanism_family=analysis.get("mechanism_family"),
            beneficiaries_text=analysis.get("beneficiaries") or [],
            losers_text=analysis.get("losers") or [],
        )
        ben_for_check = analysis["asset_selection"]["cleaned_beneficiary_tickers"]
        los_for_check = analysis["asset_selection"]["cleaned_loser_tickers"]
    except Exception:
        _api._log.warning(
            "movers backfill asset_selection failed; using raw LLM lists",
            exc_info=True,
        )
        analysis["asset_selection"] = {}
        ben_for_check = list(raw_ben)
        los_for_check = list(raw_los)

    fallback_used = False
    if not ben_for_check and not los_for_check:
        # Backfill path: when classify_and_rank_assets has nothing to
        # work with (LLM emitted no beneficiary_tickers / loser_tickers),
        # hoist symbols out of the ranked asset buckets and the legacy
        # ``assets_to_watch`` so /market_check still gets a real input.
        # Hedge/signal symbols are intentionally skipped — VIX/DXY etc.
        # are watch instruments, not beneficiaries.
        fallback = _fallback_ticker_symbols_from_analysis(analysis)
        if fallback:
            ben_for_check = fallback
            fallback_used = True

    mkt = _api.market_check(ben_for_check, los_for_check, event_date=event_date)
    _run_post_market_overlays(
        analysis,
        mkt,
        headline,
        mech_text,
        rates_for_overlays,
        stress_for_overlays,
        stage,
        event_date=event_date,
    )

    if existing_event and existing_event.get("id"):
        from db import update_event_market_refresh
        persisted = update_event_market_refresh(
            int(existing_event["id"]),
            mkt.get("tickers") or [],
            mkt.get("note") or "",
            datetime.now().isoformat(timespec="seconds"),
        )
    else:
        from db import get_events_fingerprint
        before = get_events_fingerprint()
        _api._persist_event(
            headline,
            stage,
            persistence,
            analysis,
            mkt,
            event_date,
            model=model_key,
        )
        after = get_events_fingerprint()
        persisted = after != before

    tickers = mkt.get("tickers") or []
    quality = _market_quality(tickers)
    status, reason = _market_status_reason(
        persisted=bool(persisted),
        with_tickers=quality["with_tickers"],
        with_returns=quality["with_returns"],
    )
    analysis_tickers_diag = {
        "beneficiary_tickers": list(raw_ben),
        "loser_tickers": list(raw_los),
        "assets_to_watch": list(raw_atw),
        "ben_for_check": list(ben_for_check),
        "los_for_check": list(los_for_check),
        "fallback_used": fallback_used,
    }
    if quality["ticker_count"] == 0:
        # Empty market_check result → operator needs to see what the
        # LLM actually emitted so the next iteration can decide whether
        # this is a Haiku output gap (no symbols anywhere) or a mapping
        # gap that survived the asset_selection + fallback hoists.
        _api._log.warning(
            "movers backfill produced 0 tickers for headline=%r "
            "analysis_beneficiary_tickers=%s analysis_loser_tickers=%s "
            "assets_to_watch=%s ben_for_check=%s los_for_check=%s "
            "fallback_used=%s",
            headline,
            raw_ben, raw_los, raw_atw,
            ben_for_check, los_for_check, fallback_used,
        )
    return {
        "status": status,
        "reason": reason,
        "outcome": _persist_outcome(bool(persisted), quality["with_returns"]),
        "analyzed": True,
        "persisted": bool(persisted),
        "market_tickers": tickers,
        "market_note": mkt.get("note"),
        "analysis_tickers": analysis_tickers_diag,
        **quality,
    }


def _bump_skip(skipped: dict, reason: str) -> None:
    skipped[reason] = skipped.get(reason, 0) + 1


def _cluster_published_dt(cluster: dict) -> datetime | None:
    """Best-effort parse of ``published_at`` into a ``datetime``.

    Accepts a YYYY-MM-DD or ISO-8601 string.  Returns ``None`` when the
    field is missing or unparseable so the caller can decide whether
    the cluster should be admitted (cheaper to admit a malformed-date
    cluster than to silently drop the whole working set).
    """
    raw = str(cluster.get("published_at") or "").strip()
    if not raw:
        return None
    candidate = raw[:19] if len(raw) >= 19 else raw
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(candidate, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _cluster_is_recent(
    cluster: dict, *, since: datetime | None,
) -> bool:
    """True when the cluster is within the recency window or undated."""
    if since is None:
        return True
    when = _cluster_published_dt(cluster)
    if when is None:
        # Undated clusters are admitted — better to spend a small slice
        # of the LLM budget on a possibly-stale cluster than to silently
        # drop the whole working set if every cluster lacks a parseable
        # ``published_at``.
        return True
    return when >= since


def _headline_is_market_relevant(headline: str) -> bool:
    """Return True for headlines with an economic/policy transmission read.

    Wraps ``news_relevance.is_relevant`` so the backfill can drop
    clearly non-market headlines (cartel arrests, sports, weather)
    before spending an LLM call on them.  Failure is fail-open: a
    relevance-module import error must not stop the backfill.
    """
    try:
        from news_relevance import is_relevant
    except Exception:
        return True
    try:
        return bool(is_relevant(headline or ""))
    except Exception:
        return True


# Lifecycle ordering used to pick the most-advanced state across the
# registry rows that share a title_key.  Mirrors db._REGISTRY_LIFECYCLE
# but kept local so this module doesn't reach into a private symbol.
_REGISTRY_LIFECYCLE_ORDER = (
    "seen", "eligible", "analyzed", "market_checked", "surfaced",
    "expired_low_impact",
)


def _registry_state_for_title_key(title_key: str) -> tuple[str | None, int | None]:
    """Return (state, event_id) for the most-advanced row matching title_key.

    Multiple sources sharing the same title_key may sit at different
    states transiently; pick the highest-rank state so the pre-LLM
    check sees the truth that "this headline has already been analyzed
    somewhere".
    """
    if not title_key:
        return None, None
    import sqlite3
    from db import DB_FILE, _db_ready
    if not _db_ready:
        return None, None
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute(
            "SELECT state, event_id FROM headline_registry "
            "WHERE title_key = ?",
            (title_key,),
        ).fetchall()
    if not rows:
        return None, None
    rank = {s: i for i, s in enumerate(_REGISTRY_LIFECYCLE_ORDER)}
    best_state: str | None = None
    best_event_id: int | None = None
    best_rank = -1
    for state, event_id in rows:
        r = rank.get(state or "seen", -1)
        if r > best_rank:
            best_rank = r
            best_state = state
            best_event_id = event_id
    return best_state, best_event_id


def _stamp_skip_reason_for_cluster(cluster: dict, reason: str) -> None:
    """Stamp last_skip_reason on registry rows matching the cluster's
    representative headline.  No-op when headline is missing/empty."""
    headline = _cluster_headline(cluster) if cluster else ""
    if not headline:
        return
    _hr.advance_state(
        title_key=_hr_dedup_key(headline),
        last_skip_reason=reason,
    )


def _backfill_preview_item(
    headline: str,
    event_date: str | None,
    action: str,
    skip_reason: str | None,
    would_call_llm: bool,
) -> dict:
    """Build a per-cluster dry-run preview entry.

    ``action`` is one of ``"would_analyze"``, ``"would_refresh_existing"``,
    ``"would_skip"``.  ``skip_reason`` is set only when ``action`` is
    ``"would_skip"`` (mirrors the eligible-loop's ``_bump_skip`` taxonomy).
    """
    return {
        "headline":              headline or "",
        "event_date":            event_date,
        "predicted_action":      action,
        "predicted_skip_reason": skip_reason,
        "would_call_llm":        bool(would_call_llm),
    }


@router.post("/movers/backfill-recent")
def movers_backfill_recent(
    limit: int = Query(
        3, ge=1, le=20,
        description="Maximum number of headlines processed past the dedup/skip gates.",
    ),
    max_llm_calls: int | None = Query(
        None, ge=0, le=20,
        description=(
            "Required cap on actual LLM invocations. Must be less than or "
            "equal to MAX_BACKFILL_LLM_CALLS. Refresh-only events (cached "
            "analysis re-running market_check) do NOT count against this budget."
        ),
    ),
    scan_limit: int = Query(25, ge=1, le=100),
    since_hours: int = Query(
        48, ge=1, le=720,
        description=(
            "Only consider clusters with ``published_at`` within the last "
            "N hours.  Clusters lacking a parseable date are admitted."
        ),
    ),
    dry_run: bool | None = Query(
        None,
        description=(
            "When omitted, BACKFILL_DRY_RUN_DEFAULT controls the default "
            "(true when unset). Pass dry_run=false to spend LLM calls."
        ),
    ),
    force_reanalyze: bool = Query(False),
    include_low_signal: bool = Query(False),
    confirm_paid: bool = Query(
        False,
        description=(
            "Required when dry_run=false AND max_llm_calls > 1.  "
            "Single-call paid backfills proceed without it; "
            "multi-call paid backfills must explicitly opt in."
        ),
    ),
):
    """Analyze/market-check recent headline clusters so mover windows can populate.

    Pulls the news cache (memory → SQLite fallback), filters to recent
    market-relevant clusters, and, when ``dry_run=false``, runs each through the same
    ``analyze_event`` → ``market_check`` → ``_persist_event`` pipeline
    the live ``/analyze`` route uses.  Capped by ``limit`` (attempts)
    and ``max_llm_calls`` (LLM-only budget) so a backfill cannot spend
    more than the caller authorised.  ``max_llm_calls`` is required even
    for dry runs so operators have to state the intended spend cap.
    The safe default is dry-run; callers must explicitly pass
    ``dry_run=false`` to create/update saved events.

    Status is ``"degraded"`` (not ``"ok"``) whenever any of:
      * the LLM (API key) is unavailable,
      * the news cache is empty,
      * no eligible clusters survive the recency / relevance filter,
      * any analyze raised,
      * provider data couldn't produce any with-returns event.

    The exact reasons land in ``diagnostics.degraded_reasons`` so
    operators (and the soon-to-be-built UI populate banner) can branch
    on the cause without parsing prose.
    """
    payload, source = _cached_news_payload()
    raw_clusters = _sort_news_clusters((payload or {}).get("clusters") or [])
    if max_llm_calls is None:
        raise HTTPException(
            status_code=400,
            detail="max_llm_calls is required for /movers/backfill-recent",
        )
    max_allowed_llm_calls = _max_backfill_llm_calls()
    if max_llm_calls > max_allowed_llm_calls:
        raise HTTPException(
            status_code=400,
            detail=(
                "max_llm_calls exceeds MAX_BACKFILL_LLM_CALLS "
                f"({max_allowed_llm_calls})"
            ),
        )

    provider = _backfill_provider()
    model = _backfill_model(provider)
    model_key = _backfill_model_key(provider, model)
    effective_dry_run = _backfill_dry_run_default() if dry_run is None else dry_run
    # Paid-backfill safety: a multi-call paid run requires an explicit
    # opt-in so a stray dry_run=false&max_llm_calls=20 cannot quietly
    # spend 20 LLM calls.  Single-call paid runs and dry runs are
    # unaffected.  Short-circuits BEFORE any LLM-spending work so the
    # blocked path costs nothing.
    if not effective_dry_run and max_llm_calls > 1 and not confirm_paid:
        raise HTTPException(
            status_code=400,
            detail=(
                "Paid backfill with max_llm_calls > 1 requires "
                "confirm_paid=true. Pass confirm_paid=true to proceed, "
                "or use max_llm_calls=1 / dry_run=true."
            ),
        )
    # Server-side kill-switch — ENABLE_PAID_ANALYSIS must be true for
    # any paid invocation to proceed.  Dry-run mode is unaffected (no
    # spend), and the previous URL-level checks (max_llm_calls cap,
    # confirm_paid) stay in force when the kill-switch is on.
    if not effective_dry_run and not _paid_analysis_enabled():
        raise HTTPException(
            status_code=403,
            detail=(
                "Paid analysis is disabled on this server. Set "
                "ENABLE_PAID_ANALYSIS=true to authorise paid LLM "
                "invocations from /movers/backfill-recent."
            ),
        )
    llm_available = _llm_available(provider)
    skipped: dict[str, int] = {}

    # An explicit 0 means "refresh cached events only, never call the LLM".
    llm_budget = max_llm_calls

    since_dt = (
        datetime.now() - timedelta(hours=since_hours)
        if since_hours and since_hours > 0 else None
    )

    diagnostics: dict = {
        "source": source,
        "since_hours": since_hours,
        "headlines_scanned": 0,
        "candidates_considered": 0,
        "analyzed": 0,
        "market_checked": 0,
        "skipped": skipped,
        "persisted": 0,
        "with_tickers": 0,
        "with_returns": 0,
        "llm_calls": 0,
        "llm_calls_budget": llm_budget,
        "llm_calls_max_allowed": max_allowed_llm_calls,
        "llm_provider": provider,
        "analysis_provider": _analysis_provider(),
        "analysis_model": model,
        "analysis_model_key": model_key,
        "failures": [],
        "llm_available": llm_available,
        "market_data_status": "unknown",
        "degraded_reasons": [],
        # Dry-run preview fields.  ``would_call_llm`` counts predicted
        # LLM invocations a paid run would make under the same params;
        # 0 in non-dry-run mode (use ``llm_calls`` for actual spend).
        # ``would_skip_paid_guard`` flags whether re-running this with
        # ``dry_run=false`` would be blocked by the paid-backfill guard.
        "would_call_llm": 0,
        "would_skip_paid_guard": bool(
            effective_dry_run and max_llm_calls > 1 and not confirm_paid
        ),
    }

    # Pre-filter: recency + market relevance.  Counted as ``filtered_*``
    # skips so the operator can see why a high-volume cluster set
    # collapsed to a small working set.
    eligible_clusters: list[dict] = []
    for cluster in raw_clusters:
        if not _cluster_is_recent(cluster, since=since_dt):
            _bump_skip(skipped, "outside_recency_window")
            _stamp_skip_reason_for_cluster(cluster, "outside_recency_window")
            continue
        headline_for_relevance = _cluster_headline(cluster)
        if (
            headline_for_relevance
            and not include_low_signal
            and not _headline_is_market_relevant(headline_for_relevance)
        ):
            _bump_skip(skipped, "irrelevant_headline")
            _stamp_skip_reason_for_cluster(cluster, "irrelevant_headline")
            continue
        eligible_clusters.append(cluster)

    # Re-rank eligible clusters: source_count is still the primary
    # signal (preserved from ``_sort_news_clusters``), but for clusters
    # at the same ``source_count`` we lift those whose headline names
    # an explicit company / asset / instrument term ahead of generic
    # macro headlines.  A backfill with one LLM-call budget should
    # spend it on a cluster Haiku is likeliest to map to public
    # tickers.  Stable on ties so the underlying recency / id order
    # from ``_sort_news_clusters`` survives.
    eligible_clusters.sort(
        key=lambda c: (
            int(c.get("source_count") or 0),
            1 if _cluster_has_asset_terms(c) else 0,
        ),
        reverse=True,
    )

    diagnostics["candidates_considered"] = len(eligible_clusters)

    items: list[dict] = []
    attempts = 0

    for cluster in eligible_clusters[:scan_limit]:
        diagnostics["headlines_scanned"] += 1
        headline = _cluster_headline(cluster)
        if not headline:
            _bump_skip(skipped, "empty_headline")
            continue
        if cluster.get("low_signal") and not include_low_signal:
            _bump_skip(skipped, "low_signal")
            continue

        # Headline-registry pre-LLM check.  Skips clusters whose
        # representative headline has already been analyzed (or has
        # expired as low-impact) without burning LLM budget.  See
        # docs/superpowers/specs/2026-05-03-headline-registry-design.md.
        registry_title_key = _hr_dedup_key(headline)
        registry_state, _registry_event_id = _registry_state_for_title_key(
            registry_title_key,
        )
        if not force_reanalyze and registry_state in (
            "analyzed", "market_checked", "surfaced",
        ):
            _bump_skip(skipped, "registry_already_analyzed")
            _hr.advance_state(
                title_key=registry_title_key,
                last_skip_reason="registry_already_analyzed",
            )
            if effective_dry_run:
                items.append(_backfill_preview_item(
                    headline, None, "would_skip",
                    "registry_already_analyzed", False,
                ))
            continue
        if not force_reanalyze and registry_state == "expired_low_impact":
            _bump_skip(skipped, "registry_expired_low_impact")
            _hr.advance_state(
                title_key=registry_title_key,
                last_skip_reason="registry_expired_low_impact",
            )
            if effective_dry_run:
                items.append(_backfill_preview_item(
                    headline, None, "would_skip",
                    "registry_expired_low_impact", False,
                ))
            continue

        event_date = _cluster_event_date(cluster)
        cached = _find_recent_saved_event(headline, event_date, model_key)
        existing_tickers = (cached or {}).get("market_tickers") or []
        if (
            cached
            and not force_reanalyze
            and _has_any_usable_return(existing_tickers)
        ):
            # ``return_1d`` alone is enough to consider the event
            # market-checked: events younger than 5 trading days can't
            # carry ``return_5d`` by physics, but a populated 1-day
            # reaction is what /movers/today consumes for them.  Re-
            # analyzing would burn LLM budget for no new signal.
            _bump_skip(skipped, "already_market_checked")
            _hr.advance_state(
                title_key=registry_title_key,
                last_skip_reason="already_market_checked",
            )
            # Cached events with usable returns are counted under
            # ``with_tickers``/``with_returns`` so the diagnostics
            # describe what state the cache is in, not just what this
            # run's provider calls produced.  ``market_checked`` is
            # intentionally NOT bumped — that counter measures market
            # provider invocations made by this run.
            if _has_tickers(existing_tickers):
                diagnostics["with_tickers"] += 1
            diagnostics["with_returns"] += 1
            if effective_dry_run:
                items.append(_backfill_preview_item(
                    headline, event_date, "would_skip",
                    "already_market_checked", False,
                ))
            continue
        if effective_dry_run:
            # Predict what a paid run with these params would do for
            # this cluster and add it to the preview.  We mirror the
            # gates that fire AFTER the dry_run check in the real path
            # (limit_reached, llm_budget_exhausted) so the preview is
            # honest about what the paid run would actually skip.  No
            # LLM or market_data calls happen here.
            needs_llm_call = not (cached and not force_reanalyze)
            if needs_llm_call and diagnostics["would_call_llm"] >= llm_budget:
                items.append(_backfill_preview_item(
                    headline, event_date, "would_skip",
                    "llm_budget_exhausted", False,
                ))
            elif attempts >= limit:
                items.append(_backfill_preview_item(
                    headline, event_date, "would_skip",
                    "limit_reached", False,
                ))
            else:
                if needs_llm_call:
                    diagnostics["would_call_llm"] += 1
                    items.append(_backfill_preview_item(
                        headline, event_date, "would_analyze",
                        None, True,
                    ))
                else:
                    items.append(_backfill_preview_item(
                        headline, event_date, "would_refresh_existing",
                        None, False,
                    ))
                attempts += 1
            _bump_skip(skipped, "dry_run")
            _hr.advance_state(
                title_key=registry_title_key,
                last_skip_reason="dry_run",
            )
            continue
        if attempts >= limit:
            _bump_skip(skipped, "limit_reached")
            _hr.advance_state(
                title_key=registry_title_key,
                last_skip_reason="limit_reached",
            )
            continue

        # LLM-budget pre-check: a fresh analysis path needs an LLM
        # call.  The cached-refresh path doesn't, so we only charge
        # the budget when we actually go through ``_fresh_analysis``.
        needs_llm_call = not (cached and not force_reanalyze)

        try:
            result: dict
            if cached and not force_reanalyze:
                result = _refresh_existing_market_event(cached)
                if result.get("status") == "skipped" and llm_available:
                    if diagnostics["llm_calls"] >= llm_budget:
                        _bump_skip(skipped, "llm_budget_exhausted")
                        _hr.advance_state(
                            title_key=registry_title_key,
                            last_skip_reason="llm_budget_exhausted",
                        )
                        continue
                    result = _fresh_analysis_market_event(
                        headline,
                        event_context=_cluster_event_context(cluster),
                        event_date=event_date,
                        provider=provider,
                        model=model,
                        model_key=model_key,
                        existing_event=cached,
                    )
                    diagnostics["llm_calls"] += 1
                elif result.get("status") == "skipped":
                    _bump_skip(skipped, result.get("reason") or "skipped")
                    items.append({
                        "headline": headline,
                        "event_date": event_date,
                        "status": "skipped",
                        "reason": result.get("reason"),
                    })
                    continue
            else:
                if not llm_available:
                    _bump_skip(skipped, "llm_unavailable")
                    _hr.advance_state(
                        title_key=registry_title_key,
                        last_skip_reason="llm_unavailable",
                    )
                    items.append({
                        "headline": headline,
                        "event_date": event_date,
                        "status": "degraded",
                        "reason": "llm_unavailable",
                    })
                    continue
                if needs_llm_call and diagnostics["llm_calls"] >= llm_budget:
                    _bump_skip(skipped, "llm_budget_exhausted")
                    _hr.advance_state(
                        title_key=registry_title_key,
                        last_skip_reason="llm_budget_exhausted",
                    )
                    continue
                result = _fresh_analysis_market_event(
                    headline,
                    event_context=_cluster_event_context(cluster),
                    event_date=event_date,
                    provider=provider,
                    model=model,
                    model_key=model_key,
                    existing_event=cached,
                )
                diagnostics["llm_calls"] += 1
        except Exception as exc:
            diagnostics["failures"].append({
                "headline": headline,
                "reason": str(exc),
            })
            attempts += 1
            continue

        attempts += 1
        diagnostics["analyzed"] += 1 if result.get("analyzed") else 0
        diagnostics["market_checked"] += 1
        diagnostics["persisted"] += 1 if result.get("persisted") else 0
        diagnostics["with_tickers"] += 1 if result.get("with_tickers") else 0
        diagnostics["with_returns"] += 1 if result.get("with_returns") else 0
        item_row: dict = {
            "headline": headline,
            "event_date": event_date,
            "status": result.get("status"),
            "reason": result.get("reason"),
            "outcome": result.get("outcome"),
            "persisted": bool(result.get("persisted")),
            "with_tickers": bool(result.get("with_tickers")),
            "with_returns": bool(result.get("with_returns")),
            "ticker_count": result.get("ticker_count", 0),
        }
        if result.get("analysis_tickers") is not None:
            item_row["analysis_tickers"] = result.get("analysis_tickers")
        items.append(item_row)
        # Headline-registry post-action stamps.  Forward-only
        # update_registry_state advances state for every registry row
        # matching this title_key; lower-rank current states get
        # promoted, equal/higher-rank rows are unchanged.
        try:
            impact_level = (
                (result.get("conviction") or {}).get("impact_level")
                if isinstance(result, dict) else None
            )
            if isinstance(result, dict) and result.get("analyzed"):
                _hr.advance_state(
                    title_key=registry_title_key,
                    new_state="analyzed",
                    event_id=result.get("event_id"),
                    impact_level=impact_level,
                    analyzed_at=datetime.now().replace(
                        microsecond=0,
                    ).isoformat(),
                )
            if isinstance(result, dict) and result.get("with_returns"):
                _hr.advance_state(
                    title_key=registry_title_key,
                    new_state="market_checked",
                )
        except Exception:
            _api._log.warning(
                "registry post-action stamp failed", exc_info=True,
            )

    # ``market_data_status`` is computed strictly from the run-level
    # counters so it always agrees with ``with_tickers``/``with_returns``
    # and the per-item outcomes.  Three states:
    #   * ``ok``       — every ticker-bearing event got returns (or the
    #                    working set had none, which isn't a provider
    #                    problem).
    #   * ``partial``  — at least one ticker-bearing event got returns
    #                    AND at least one didn't (mixed run).
    #   * ``degraded`` — every ticker-bearing event came back without
    #                    returns (full provider failure).
    if diagnostics["with_tickers"] == 0:
        diagnostics["market_data_status"] = "ok"
    elif diagnostics["with_returns"] == 0:
        diagnostics["market_data_status"] = "degraded"
    elif diagnostics["with_returns"] < diagnostics["with_tickers"]:
        diagnostics["market_data_status"] = "partial"
    else:
        diagnostics["market_data_status"] = "ok"

    # Build the explicit degraded-reasons list so the caller can branch
    # on the exact cause.  Reasons reflect what actually happened — a
    # missing API key only flags ``llm_unavailable`` when the run hit
    # a path that needed the LLM (i.e., ``skipped["llm_unavailable"]``
    # incremented).  A backfill that successfully refreshed cached
    # events without ever needing the LLM stays ``"ok"``.
    degraded: list[str] = []
    if skipped.get("llm_unavailable"):
        degraded.append("llm_unavailable")
    if not raw_clusters:
        degraded.append("news_cache_empty")
    elif not eligible_clusters:
        degraded.append("no_eligible_clusters")
    if diagnostics["failures"]:
        degraded.append("analyze_failures")
    # Provider-side reasons mirror ``market_data_status`` so the two
    # always agree.  ``market_data_unavailable`` is reserved for the
    # full-failure case; ``partial_market_data`` flags the mixed run
    # so a consumer can tell "some data is fine, some is missing"
    # apart from "nothing came back at all".
    if diagnostics["with_tickers"] > 0:
        if diagnostics["with_returns"] == 0:
            degraded.append("market_data_unavailable")
        elif diagnostics["with_returns"] < diagnostics["with_tickers"]:
            degraded.append("partial_market_data")
    diagnostics["degraded_reasons"] = degraded

    # Status reflects the explicit ``degraded_reasons`` list — the same
    # signal the response surfaces to callers.  ``market_data_status``
    # is now redundant for status purposes (its degraded case is
    # mirrored in ``degraded_reasons["market_data_unavailable"]``) but
    # retained in diagnostics for backwards-compat.
    status = "ok"
    if degraded or not diagnostics["headlines_scanned"]:
        status = "degraded"
    return _api._sanitize_floats({
        "status": status,
        "dry_run": effective_dry_run,
        "limit": limit,
        "max_llm_calls": llm_budget,
        "scan_limit": scan_limit,
        "since_hours": since_hours,
        "diagnostics": diagnostics,
        "items": items,
    })


@router.get("/movers/backfill-preview")
def movers_backfill_preview(
    limit: int = Query(
        25, ge=1, le=100,
        description="Cap on the number of preview items returned.",
    ),
    since_hours: int = Query(
        48, ge=1, le=720,
        description=(
            "Recency window in hours.  Mirrors the ``since_hours`` "
            "filter on /movers/backfill-recent so preview eligibility "
            "matches what the paid run would consider."
        ),
    ),
    include_low_signal: bool = Query(
        False,
        description=(
            "When true, low-signal clusters and headlines that fail "
            "``news_relevance.is_relevant`` are still classified as "
            "candidates.  Mirrors the backfill flag of the same name."
        ),
    ),
    force_reanalyze: bool = Query(
        False,
        description=(
            "When true, registry ``analyzed`` / ``market_checked`` / "
            "``surfaced`` / ``expired_low_impact`` rows and cached "
            "events with usable returns are NOT treated as already-"
            "analyzed.  Mirrors the backfill flag — defaults to false "
            "so the preview matches a normal paid run."
        ),
    ),
):
    """Zero-cost preview of /movers/backfill-recent eligibility.

    Reads the same news cache (memory → SQLite, no fetch), applies the
    same recency / relevance / low-signal pre-filters, sorts the
    survivors with the same ``(source_count, has_asset_terms)`` rule,
    and classifies each cluster against registry state and the cached-
    event TTL — but never calls the LLM, ``market_check``, or
    ``_persist_event``, never writes to ``headline_registry``, and
    never invalidates a cache.  Pure read of in-memory + SQLite state.

    The paid-backfill cost guard on ``POST /movers/backfill-recent`` is
    intentionally untouched — this endpoint exists so the operator can
    inspect what *would* run before authorising the spend.
    """
    payload, source = _cached_news_payload()
    raw_clusters = _sort_news_clusters((payload or {}).get("clusters") or [])

    provider = _backfill_provider()
    model = _backfill_model(provider)
    model_key = _backfill_model_key(provider, model)
    llm_available = _llm_available(provider)

    since_dt = (
        datetime.now() - timedelta(hours=since_hours)
        if since_hours and since_hours > 0 else None
    )

    skip_reasons: dict[str, int] = {}
    counts = {
        "scanned": len(raw_clusters),
        "considered": 0,
        "eligible": 0,
        "already_analyzed": 0,
        "would_call_llm": 0,
    }

    # Pre-filter: recency + relevance — same gate as backfill.  Pre-
    # filter rejections are aggregated into ``skip_reasons`` for visi-
    # bility but do NOT show up in the per-item list.  ``low_signal``
    # is handled inside the per-cluster loop below to mirror the
    # backfill exactly (the backfill applies it after the secondary
    # sort, so a high-source-count low_signal cluster still gets seen
    # by the registry/cache check on the preview).
    eligible_clusters: list[dict] = []
    for cluster in raw_clusters:
        if not _cluster_is_recent(cluster, since=since_dt):
            _bump_skip(skip_reasons, "outside_recency_window")
            continue
        headline_for_relevance = _cluster_headline(cluster)
        if (
            headline_for_relevance
            and not include_low_signal
            and not _headline_is_market_relevant(headline_for_relevance)
        ):
            _bump_skip(skip_reasons, "irrelevant_headline")
            continue
        eligible_clusters.append(cluster)

    # Score once, attach to the cluster dict so the per-item loop below
    # can surface ``rank_score`` + ``rank_factors`` on each preview row
    # without recomputing.  Sort by score, then fall back to the legacy
    # ``(source_count, has_asset_terms)`` tiebreak so equal-score
    # clusters land in a stable order across runs.
    cluster_scores: list[tuple[dict, float, dict]] = []
    for cluster in eligible_clusters:
        score, factors = _score_cluster_for_preview(cluster)
        cluster_scores.append((cluster, score, factors))
    cluster_scores.sort(
        key=lambda triple: (
            triple[1],
            int(triple[0].get("source_count") or 0),
            1 if _cluster_has_asset_terms(triple[0]) else 0,
        ),
        reverse=True,
    )
    eligible_clusters = [t[0] for t in cluster_scores]
    score_by_id = {id(t[0]): (t[1], t[2]) for t in cluster_scores}

    items: list[dict] = []
    for cluster in eligible_clusters:
        if len(items) >= limit:
            break
        headline = _cluster_headline(cluster)
        if not headline:
            _bump_skip(skip_reasons, "empty_headline")
            continue

        counts["considered"] += 1

        skip_reason: str | None = None
        already_analyzed = False

        if cluster.get("low_signal") and not include_low_signal:
            skip_reason = "low_signal"
        else:
            registry_title_key = _hr_dedup_key(headline)
            registry_state, _eid = _registry_state_for_title_key(
                registry_title_key,
            )
            if not force_reanalyze and registry_state in (
                "analyzed", "market_checked", "surfaced",
            ):
                skip_reason = "registry_already_analyzed"
                already_analyzed = True
            elif not force_reanalyze and registry_state == "expired_low_impact":
                skip_reason = "registry_expired_low_impact"
                already_analyzed = True
            else:
                event_date = _cluster_event_date(cluster)
                cached = _find_recent_saved_event(
                    headline, event_date, model_key,
                )
                existing_tickers = (cached or {}).get("market_tickers") or []
                if (
                    cached
                    and not force_reanalyze
                    and _has_any_usable_return(existing_tickers)
                ):
                    skip_reason = "already_market_checked"
                    already_analyzed = True

        would_call_llm = skip_reason is None and llm_available

        if skip_reason is None:
            counts["eligible"] += 1
        else:
            _bump_skip(skip_reasons, skip_reason)
        if already_analyzed:
            counts["already_analyzed"] += 1
        if would_call_llm:
            counts["would_call_llm"] += 1

        rank_score, rank_factors = score_by_id.get(
            id(cluster), (0.0, _headline_keyword_signals("")),
        )
        if "source_count" not in rank_factors:
            rank_factors = {
                "source_count":      int(cluster.get("source_count") or 0),
                "high_tier_sources": 0,
                "has_asset_terms":   False,
                **rank_factors,
            }
        items.append({
            "headline": headline,
            "source_count": int(cluster.get("source_count") or 0),
            "published_at": str(cluster.get("published_at") or "") or None,
            "skip_reason": skip_reason,
            "skip_reason_label": _skip_reason_label(skip_reason),
            "already_analyzed": already_analyzed,
            "would_call_llm": would_call_llm,
            "rank_score":   round(float(rank_score), 3),
            "rank_factors": rank_factors,
            "rank_explanation": _rank_explanation(rank_factors),
        })

    return _api._sanitize_floats({
        "items": items,
        "counts": counts,
        "skip_reasons": skip_reasons,
        "filters": {
            "limit": limit,
            "since_hours": since_hours,
            "include_low_signal": include_low_signal,
            "force_reanalyze": force_reanalyze,
        },
        "news_source": source,
        "llm_available": llm_available,
        "llm_provider": provider,
        "analysis_model": model,
        "analysis_model_key": model_key,
    })


@router.post("/movers/backfill-candidate")
def movers_backfill_candidate(
    headline: str = Query(
        ...,
        min_length=1,
        description=(
            "Headline of the preview candidate to analyze.  Matched "
            "against the cached news payload via the same dedup-key "
            "function the registry uses, so minor punctuation / case "
            "differences resolve to the same cluster."
        ),
    ),
    confirm_paid: bool = Query(
        False,
        description=(
            "Required.  Must be true — this is the explicit paid "
            "confirmation gate.  Mirrors the multi-call paid-backfill "
            "guard on /movers/backfill-recent: a paid LLM invocation "
            "from a single-candidate request must still be opted into."
        ),
    ),
    since_hours: int = Query(
        72, ge=1, le=720,
        description=(
            "Recency window for matching the headline against the news "
            "cache.  A cluster older than this is treated as not found "
            "so a stale headline can't be re-analyzed by accident."
        ),
    ),
    force_reanalyze: bool = Query(
        False,
        description=(
            "Mirrors the /movers/backfill-recent flag — bypasses the "
            "registry already-analyzed / cached-event short-circuits."
        ),
    ),
    include_low_signal: bool = Query(
        False,
        description=(
            "Mirrors the /movers/backfill-recent flag — admits low-"
            "signal clusters and headlines that fail the relevance gate."
        ),
    ),
):
    """Analyze exactly one preview candidate identified by ``headline``.

    Hard cap: at most one LLM call per request.  The cached-event
    refresh path (no LLM, no new analysis) is reused unchanged so a
    stale-tickers refresh on an existing event doesn't burn an LLM
    invocation that the operator authorised for fresh analysis.

    All other gates (registry state, market-checked cache, recency,
    relevance, low_signal) match /movers/backfill-recent so behaviour
    is consistent — this endpoint is a single-row variant of the same
    pipeline, not a parallel implementation.
    """
    if not confirm_paid:
        raise HTTPException(
            status_code=400,
            detail=(
                "confirm_paid=true is required for "
                "/movers/backfill-candidate (single paid LLM invocation)."
            ),
        )
    # Server-side kill-switch — every invocation of this endpoint is
    # paid by design, so ENABLE_PAID_ANALYSIS must be true regardless
    # of the per-request flags.  Short-circuits BEFORE any provider /
    # LLM / persistence work.
    if not _paid_analysis_enabled():
        raise HTTPException(
            status_code=403,
            detail=(
                "Paid analysis is disabled on this server. Set "
                "ENABLE_PAID_ANALYSIS=true to authorise paid LLM "
                "invocations from /movers/backfill-candidate."
            ),
        )

    provider = _backfill_provider()
    model = _backfill_model(provider)
    model_key = _backfill_model_key(provider, model)
    llm_available = _llm_available(provider)

    base_response: dict = {
        "headline": headline,
        "analyzed": False,
        "persisted": False,
        "with_tickers": False,
        "with_returns": False,
        "ticker_count": 0,
        "event_id": None,
        "llm_calls": 0,
        "llm_provider": provider,
        "analysis_model": model,
        "analysis_model_key": model_key,
    }

    def _result(status: str, reason: str | None, **extra) -> dict:
        return _api._sanitize_floats({
            **base_response,
            "status": status,
            "reason": reason,
            **extra,
        })

    if not llm_available:
        # Fail fast before reading the cache so the operator sees the
        # real cause; no LLM call is attempted, no registry stamps move.
        return _result("degraded", "llm_unavailable")

    payload, _source = _cached_news_payload()
    raw_clusters = (payload or {}).get("clusters") or []
    since_dt = (
        datetime.now() - timedelta(hours=since_hours)
        if since_hours and since_hours > 0 else None
    )

    target_key = _hr_dedup_key(headline)
    cluster: dict | None = None
    for c in raw_clusters:
        if not isinstance(c, dict):
            continue
        if _hr_dedup_key(_cluster_headline(c)) == target_key:
            cluster = c
            break
    if cluster is None:
        return _result("skipped", "candidate_not_found")
    if not _cluster_is_recent(cluster, since=since_dt):
        return _result("skipped", "outside_recency_window")
    candidate_headline = _cluster_headline(cluster)
    if (
        candidate_headline
        and not include_low_signal
        and not _headline_is_market_relevant(candidate_headline)
    ):
        return _result("skipped", "irrelevant_headline")
    if cluster.get("low_signal") and not include_low_signal:
        return _result("skipped", "low_signal")

    registry_title_key = _hr_dedup_key(candidate_headline)
    registry_state, _ = _registry_state_for_title_key(registry_title_key)
    if not force_reanalyze and registry_state in (
        "analyzed", "market_checked", "surfaced",
    ):
        _hr.advance_state(
            title_key=registry_title_key,
            last_skip_reason="registry_already_analyzed",
        )
        return _result("skipped", "registry_already_analyzed")
    if not force_reanalyze and registry_state == "expired_low_impact":
        _hr.advance_state(
            title_key=registry_title_key,
            last_skip_reason="registry_expired_low_impact",
        )
        return _result("skipped", "registry_expired_low_impact")

    event_date = _cluster_event_date(cluster)
    cached = _find_recent_saved_event(candidate_headline, event_date, model_key)
    existing_tickers = (cached or {}).get("market_tickers") or []
    if (
        cached
        and not force_reanalyze
        and _has_any_usable_return(existing_tickers)
    ):
        _hr.advance_state(
            title_key=registry_title_key,
            last_skip_reason="already_market_checked",
        )
        return _result(
            "skipped", "already_market_checked",
            event_id=cached.get("id"),
        )

    # ── Single LLM-spending pass ───────────────────────────────────────
    # The cached-but-stale path goes through ``_refresh_existing_market_event``
    # first (no LLM); only when it explicitly returns ``status='skipped'``
    # because the row needs fresh analysis do we promote to
    # ``_fresh_analysis_market_event`` — and that's the one and only LLM
    # call this endpoint authorises.
    try:
        if cached and not force_reanalyze:
            result = _refresh_existing_market_event(cached)
            if result.get("status") == "skipped":
                # Refresh helper signalled "needs fresh analysis" — spend
                # the single authorised LLM call.
                result = _fresh_analysis_market_event(
                    candidate_headline,
                    event_context=_cluster_event_context(cluster),
                    event_date=event_date,
                    provider=provider,
                    model=model,
                    model_key=model_key,
                    existing_event=cached,
                )
                base_response["llm_calls"] = 1
        else:
            result = _fresh_analysis_market_event(
                candidate_headline,
                event_context=_cluster_event_context(cluster),
                event_date=event_date,
                provider=provider,
                model=model,
                model_key=model_key,
                existing_event=cached,
            )
            base_response["llm_calls"] = 1
    except Exception as exc:
        _api._log.warning(
            "/movers/backfill-candidate analyze failed for %r",
            candidate_headline, exc_info=True,
        )
        return _result("degraded", f"analyze_failed: {exc}")

    if not isinstance(result, dict):
        return _result("degraded", "invalid_pipeline_result")

    # Registry forward-only stamps so subsequent previews / runs see the
    # advanced state.  Mirrors /movers/backfill-recent post-action stamps.
    try:
        impact_level = (result.get("conviction") or {}).get("impact_level")
        if result.get("analyzed"):
            _hr.advance_state(
                title_key=registry_title_key,
                new_state="analyzed",
                event_id=result.get("event_id"),
                impact_level=impact_level,
                analyzed_at=datetime.now().replace(
                    microsecond=0,
                ).isoformat(),
            )
        if result.get("with_returns"):
            _hr.advance_state(
                title_key=registry_title_key,
                new_state="market_checked",
            )
    except Exception:
        _api._log.warning(
            "/movers/backfill-candidate registry stamp failed", exc_info=True,
        )

    return _result(
        result.get("status") or ("analyzed" if result.get("analyzed") else "skipped"),
        result.get("reason"),
        analyzed=bool(result.get("analyzed")),
        persisted=bool(result.get("persisted")),
        with_tickers=bool(result.get("with_tickers")),
        with_returns=bool(result.get("with_returns")),
        ticker_count=int(result.get("ticker_count") or 0),
        event_id=result.get("event_id"),
        outcome=result.get("outcome"),
    )


def _project(envelope: dict, *, include_meta: bool):
    """Return the bare items list by default; surface the full
    ``{items, meta}`` envelope only when the caller opts in via
    ``?include_meta=true``.  The envelope is computed once internally
    so diagnostics stay available without breaking the legacy bare-list
    contract every existing consumer reads.
    """
    if include_meta is True:
        return envelope
    if isinstance(envelope, dict) and "items" in envelope:
        return envelope["items"]
    return envelope


@router.get("/market-movers")
def market_movers(
    limit: int = Query(5, ge=1, le=100),
    include_meta: bool = Query(False),
):
    """Return saved events with confirmed market moves, ranked by impact.

    Routed through the shared movers_cache pattern (same as /movers/weekly,
    /movers/yearly, /movers/persistent) so ranking, TTL-based freshness and
    event-fingerprint invalidation behaviour are identical across every
    mover surface.  The 48h window is preserved by the ``market_movers``
    slice definition in movers_cache.

    Default response is a bare list of mover cards.  Pass
    ``?include_meta=true`` to receive the ``{items, meta}`` envelope
    that carries surfaced_count, cluster/family counts, and (when the
    list is empty) the diagnostics block explaining why.
    """
    envelope = _sanitize_movers_with_meta(
        movers_cache.get_slice(
            "market_movers",
            limit=limit,
            ttl_seconds=_api._MARKET_MOVERS_TTL,
        ),
        window="market",
        diagnostics=_time_window_diagnostics("market_movers"),
    )
    return _project(envelope, include_meta=include_meta)


@router.get("/movers/today")
def movers_today(
    limit: int = Query(10, ge=1, le=100),
    include_meta: bool = Query(False),
):
    """Return analyzed events from the last 24 hours with any confirmed ticker move.

    Default response is a bare list; ``?include_meta=true`` returns the
    diagnostics envelope.
    """
    raw = _api.movers_today(limit=limit)
    # Read-time expiry filter — runs every call, NOT inside the
    # _TODAYS_MOVERS_CACHE build, so rows can't expire mid-TTL invisibly.
    # See docs/superpowers/specs/2026-05-03-headline-registry-design.md.
    filtered = _hr.filter_expired_low_impact(raw or [])
    envelope = _sanitize_movers_with_meta(
        filtered,
        window="today",
        diagnostics=_time_window_diagnostics("today"),
    )
    # Surface which today-window cutoff actually produced the items
    # (24h preferred, 48h fallback when 24h is empty).  Lifted onto
    # ``meta`` directly so the field is visible whether or not the
    # diagnostics block was attached (the diagnostics block is gated
    # on a non-empty events_scanned/rejections count, which a
    # genuinely-empty DB can't satisfy).
    window_hours = int(_api._TODAYS_MOVERS_CACHE.get("window_hours", _api._TODAY_WINDOW_HOURS))
    fallback_active = window_hours > _api._TODAY_WINDOW_HOURS
    has_items = bool(envelope.get("items")) if isinstance(envelope, dict) else False
    if not has_items:
        note = (
            "No event-linked moves in the last 48 hours." if fallback_active
            else "No event-linked moves in the last 24 hours."
        )
    elif fallback_active:
        note = (
            "No fresh moves in the last 24 hours; "
            "showing the most recent session (48h window)."
        )
    else:
        note = "Showing fresh moves from the last 24 hours."
    if isinstance(envelope, dict) and isinstance(envelope.get("meta"), dict):
        envelope["meta"]["today_window_hours_used"] = window_hours
        envelope["meta"]["today_window_fallback_active"] = fallback_active
        envelope["meta"]["today_window_note"] = note
    return _project(envelope, include_meta=include_meta)


@router.get("/movers/weekly")
def movers_weekly(
    limit: int = Query(10, ge=1, le=100),
    include_meta: bool = Query(False),
):
    envelope = _sanitize_movers_with_meta(
        movers_cache.get_slice("weekly", limit=limit, ttl_seconds=_api._WEEKLY_MOVERS_TTL),
        window="weekly",
        diagnostics=_time_window_diagnostics("weekly"),
    )
    return _project(envelope, include_meta=include_meta)


@router.get("/movers/yearly")
def movers_yearly(
    limit: int = Query(10, ge=1, le=100),
    include_meta: bool = Query(False),
):
    # Yearly surface is not listed in the task's canonical window set,
    # but the route exists today and has live consumers.  Project it
    # onto the same UI shape under the "persistent" label — it is a
    # long-window repricing read in spirit — so the route keeps a
    # stable shape without adding a new window token.
    envelope = _sanitize_movers(
        movers_cache.get_slice("yearly", limit=limit, ttl_seconds=_api._YEARLY_MOVERS_TTL),
        window="persistent",
    )
    return _project(envelope, include_meta=include_meta)


@router.get("/movers/persistent")
def movers_persistent(
    limit: int = Query(12, ge=1, le=100),
    include_meta: bool = Query(False),
):
    """High-conviction "Still Moving Markets" surface.

    Unlike /movers/today (demote) or /movers/weekly (demote),
    /movers/persistent enforces a hard high-conviction gate on every
    surfaced row — including any rows the slice's Phase-2 fallback
    contributed.  See ``is_high_conviction_persistent`` for the rule.

    Default response is a bare list; ``?include_meta=true`` returns the
    diagnostics envelope.
    """
    raw = movers_cache.get_slice(
        "persistent",
        limit=_PERSISTENT_OVERFETCH,
        ttl_seconds=_api._PERSISTENT_MOVERS_TTL,
    )
    eligible = [c for c in (raw or []) if is_high_conviction_persistent(c)]
    diagnostics = movers_cache.diagnose_persistent_cards(raw, eligible)
    envelope = _sanitize_movers_with_meta(
        eligible[:limit],
        window="persistent",
        diagnostics=diagnostics,
    )
    return _project(envelope, include_meta=include_meta)
