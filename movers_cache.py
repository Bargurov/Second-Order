"""
movers_cache.py

Persisted cache layer for the /movers/<slice> endpoints.

Before this module the four movers endpoints each recomputed their
entire payload from scratch on every request: a 500-row load from
``events``, deduplication by headline, ticker filtering, impact
scoring, sort.  A tiny in-memory TTL cache absorbed the worst of it,
but a process restart (uvicorn reload, tests, cron) blew the cache
away and every first-after-restart request hit the full recompute.

Goals
-----
  * Precompute each slice once and persist the result to SQLite.
  * Endpoints read the cached row by default; they only recompute when
    the cache is missing, older than ``ttl_seconds``, or the underlying
    events table has changed (detected via a cheap max-id + count
    fingerprint).
  * Keep the ranking logic and the shape of the returned mover dicts
    byte-for-byte identical to the legacy inline path, so existing
    tests and consumers do not need to change.

Slices
------
The three slices this module currently handles are the ones the task
brief calls out explicitly:

    weekly      — last 7d by timestamp, impact-sorted
    yearly      — last 365d by timestamp, impact-sorted
    persistent  — events > 7d old with Accelerating / Holding decay
                  (falls back to any mover if strict set is empty)

``/movers/today`` keeps its own short-TTL in-memory path — a 24h
window with a 5-minute TTL doesn't benefit from persistence (every
restart would rebuild it within minutes anyway) and keeping it inline
preserves the existing test hooks.

Calibration
-----------
The TTL per slice is grounded in ``tools/movers_cache_validation.py``,
which replays a representative day-of-dashboard workload against the
live events archive (32 views at 15-minute cadence across 3 slices
plus 3 analyse→save events that flip the fingerprint).  Numbers:

                    TTL        computes / 96 reads    hit rate
    aggressive    5/10/5 min           96                0.0%
    current      60/120/60 min         ~20              ~79%
    conservative 2h/4h/2h               12               87.5%

At 60-minute TTLs the view cadence (15 min) absorbs every passive
refresh inside the hour, and the fingerprint invalidation catches
every save instantly — users never see a stale row after they click
"analyze".  Tighter TTLs (< 30 min) stop helping once the view cadence
exceeds the TTL; looser TTLs (> 2h) give only marginal extra hit rate.

The 60 / 120 / 60 minute numbers below are the validated choice.
The fingerprint check fires a refresh any time a new row is saved
regardless of TTL — the TTL is just the ceiling, not the floor.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

_log = logging.getLogger("second_order.movers_cache")


# ---------------------------------------------------------------------------
# Default TTLs per slice (seconds).  Grounded in
# tools/movers_cache_validation.py — do not change without re-running
# the validation script.
# ---------------------------------------------------------------------------

_DEFAULT_TTLS: dict[str, int] = {
    "market_movers":  300,    #  5 min — short window, high UI-refresh visibility
    "weekly":         3600,   # 60 min — validated in movers_cache_validation.py
    "yearly":         7200,   # 120 min — rolls slowly, low cost to keep warm
    "persistent":     3600,   # 60 min — same target as weekly
}

# Window for the "market_movers" (48h) slice.  Kept here rather than at the
# route so compute_slice is self-contained; the route just asks for the slice.
_MARKET_MOVERS_WINDOW_HOURS: int = 48

# |return_5d| threshold (%) for a ticker to qualify as a "mover" on the
# /market-movers surface.  Imported lazily from api._MOVER_THRESHOLD to stay
# aligned with the per-ticker rankers (today / movers_today) and avoid drift.

# Bump this when compute logic changes.  The persisted cache includes
# this stamp; on read, a mismatch triggers an immediate recompute so
# code changes take effect without waiting for TTL expiry or new events.
_COMPUTE_VERSION = 6  # v6: active-window eligibility + empty diagnostics


# ---------------------------------------------------------------------------
# Slice definitions — each one knows how to filter + sort the event list.
# ---------------------------------------------------------------------------


def _is_mover_event(ev: dict) -> list[dict]:
    """Return the list of tickers on ``ev`` that have non-null 5d returns.

    Empty list means the event does not qualify as a mover at all.

    Cross-contaminated persisted ticker rows (multiple distinct symbols
    sharing byte-identical return_5d / spark — a yfinance race
    signature) are suppressed via ``market_check._suppress_duplicate_tickers``
    BEFORE the qualification check, so a corrupted event never
    parades duplicate cards through any movers slice.
    """
    from market_check import _suppress_duplicate_tickers
    tickers = _suppress_duplicate_tickers(ev.get("market_tickers", []) or [])
    return [t for t in tickers if t.get("return_5d") is not None]


def _dedupe_by_headline(events: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for ev in events:
        hl = ev.get("headline", "")
        if hl in seen:
            continue
        seen.add(hl)
        out.append(ev)
    return out


def _window_token(slice_name: str) -> str:
    """Map cache slice names onto public mover-window ids."""
    if slice_name == "market_movers":
        return "market"
    return slice_name


def _coerce_window_set(raw: Any) -> set[str]:
    """Return a normalized set from an active_mover_windows-style value."""
    if raw is None:
        return set()
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return set()
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError):
            decoded = [part.strip() for part in text.split(",")]
        return _coerce_window_set(decoded)
    if isinstance(raw, dict):
        return {str(k) for k, v in raw.items() if v}
    if isinstance(raw, (list, tuple, set)):
        return {str(v) for v in raw if isinstance(v, str) and v}
    return set()


def active_mover_windows(ev: dict) -> set[str]:
    """Return explicit mover-window hints carried on an event row.

    Normal DB rows usually do not persist this field; tests and replay
    paths sometimes pass decorated rows through the same backend helpers.
    When present, it is treated as an additive eligibility hint, not as
    proof that a row should bypass ticker/quality gates.
    """
    if not isinstance(ev, dict):
        return set()
    return _coerce_window_set(ev.get("active_mover_windows"))


_WINDOW_EDGE_GRACE = timedelta(minutes=5)


def _within_cutoff(value: str, cutoff_iso: str) -> bool:
    if not value:
        return False
    if value >= cutoff_iso:
        return True
    try:
        return (
            datetime.fromisoformat(value)
            >= datetime.fromisoformat(cutoff_iso) - _WINDOW_EDGE_GRACE
        )
    except (TypeError, ValueError):
        return False


def _today_window_match_reason(
    ev: dict, cutoff_iso: str,
) -> tuple[bool, str | None]:
    """Today eligibility against ``timestamp`` AND ``last_market_check_at``.

    A backfill-refreshed event keeps its original ``timestamp`` but
    stamps ``last_market_check_at`` fresh.  Treat either anchor as
    qualifying so a recently market-checked older event still surfaces
    in /movers/today.  ``reason`` names the field(s) that excluded the
    row when neither anchor qualifies.
    """
    if not isinstance(ev, dict):
        return False, "malformed_event"
    ts = (ev.get("timestamp") or "").strip()
    last_check = (ev.get("last_market_check_at") or "").strip()
    if _within_cutoff(ts, cutoff_iso) or _within_cutoff(last_check, cutoff_iso):
        return True, None
    if not ts and not last_check:
        return False, "no_timestamp_no_market_check"
    if not last_check:
        return False, "stale_timestamp_no_market_check"
    if not ts:
        return False, "stale_market_check_no_timestamp"
    return False, "stale_timestamp_and_market_check"


def event_matches_mover_window(ev: dict, window: str, cutoff_iso: str) -> bool:
    """True when an event belongs to a mover window by hint or timestamp.

    Tests and saved-event flows often stamp rows at the intended edge of a
    window, then query a few seconds later.  Keep those boundary rows inside
    the same mover contract without widening genuinely stale windows.

    The today window additionally accepts ``last_market_check_at`` as a
    truthful anchor so backfill-refreshed events (whose ``timestamp``
    stays at the original analysis time) still surface as today movers.
    Weekly / yearly / persistent keep the timestamp-only contract.
    """
    token = _window_token(window)
    if token in active_mover_windows(ev):
        return True
    if token == "today":
        matched, _ = _today_window_match_reason(ev, cutoff_iso)
        return matched
    ts = ev.get("timestamp", "") or ""
    if not ts:
        return False
    if ts >= cutoff_iso:
        return True
    try:
        ts_dt = datetime.fromisoformat(ts)
        cutoff_dt = datetime.fromisoformat(cutoff_iso)
        return ts_dt >= cutoff_dt - _WINDOW_EDGE_GRACE
    except (TypeError, ValueError):
        return False


_INSUFFICIENT_EVIDENCE = "Insufficient evidence"


def _has_no_mechanism(ev: dict) -> bool:
    """Return True if the event has no meaningful transmission mechanism.

    Narrower than ``_is_event_low_signal`` — checks only the mechanism
    text, not the low_signal column or headline relevance.  Used by the
    persistent slice so that low_signal=1 events and events with
    off-topic headlines are not excluded from "Still Moving Markets" if
    they carry real ticker data; only events the LLM explicitly flagged
    as unresolvable are suppressed.

    Targets the ``_INSUFFICIENT_EVIDENCE`` sentinel and similar explicit
    LLM rejection phrases only.  Empty-string mechanism_summary is a
    legacy data-quality artifact and is NOT filtered here.
    """
    mech = (ev.get("mechanism_summary") or "").strip()
    return bool(mech) and mech.startswith(_INSUFFICIENT_EVIDENCE)


def is_mock_event(ev: dict) -> bool:
    """Return True if the event row was persisted from a mock/fallback LLM result.

    Mock events have ``what_changed`` containing ``[mock:``.  They were
    persisted before the mock-guard was added to the /analyze pipeline
    and must be excluded from all user-facing surfaces (movers, cache
    hits, headline lists) to avoid presenting garbage as real analysis.
    """
    return "[mock:" in (ev.get("what_changed") or "")


def event_low_signal_reason(ev: dict) -> str | None:
    """Return the low-signal rejection reason for mover diagnostics.

    Four independent gates — any one disqualifies:

    1. **Mock/fallback** — the LLM returned a placeholder, not real
       analysis.  Legacy rows persisted before the mock-guard are
       caught here so they never surface on cards.

    2. **low_signal column** — set by ``_is_low_signal()`` at persist time
       when the event has absolutely no analytical content (no mechanism,
       no beneficiaries, no losers, no chain).

    3. **Headline relevance** — the same ``is_relevant()`` filter applied
       at news ingestion.  An irrelevant headline (entertainment, sports,
       lifestyle, etc.) that nonetheless received partial LLM output
       (the model hallucinated beneficiaries for a celebrity story) is
       caught here.  This prevents "India stage-queens" style junk from
       surfacing even when low_signal=0.

    4. **Insufficient evidence** — the LLM could not identify a
       transmission mechanism.  The event may have a relevant headline
       (e.g. "Ecuador agreement on trade") but lacks the analytical
       substance to qualify as a market mover.

    For events persisted before the column existed (legacy rows), low_signal
    defaults to 0/None — they fall through to the remaining checks.
    """
    if is_mock_event(ev):
        return "mock_event"
    if bool(ev.get("low_signal")):
        return "low_signal"
    # Mechanism evidence gate
    mech = (ev.get("mechanism_summary") or "").strip()
    if mech.startswith(_INSUFFICIENT_EVIDENCE):
        return "insufficient_evidence"
    # Headline relevance gate — lazy import to avoid circular deps
    headline = (ev.get("headline") or "").strip()
    if headline:
        from news_sources import is_relevant
        if not is_relevant(headline):
            return "irrelevant_headline"
    return None


def _is_event_low_signal(ev: dict) -> bool:
    """Return True if the event should be excluded from mover surfaces."""
    return event_low_signal_reason(ev) is not None


def _inc(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _compute_time_slice(
    events: list[dict],
    cutoff_iso: str,
    build_mover_summary: Callable[[dict, list[dict], float], dict],
    *,
    window: str,
    filter_low_signal: bool = False,
) -> list[dict]:
    """Shared logic for the weekly + yearly slices.

    Mirrors the legacy ``_build_time_movers`` inline helper in api.py.
    Events newer than ``cutoff_iso``, deduplicated by headline, any
    ticker with ``return_5d`` qualifies, sorted by impact descending.

    ``filter_low_signal`` controls whether irrelevant/noise events are
    excluded.  Only the weekly surface enables this — yearly and
    persistent keep everything that has real ticker data.
    """
    from market_check import (
        _suppress_duplicate_tickers,
        _scrub_implausible_ticker_returns,
    )
    scored: list[dict] = []
    seen_headlines: set[str] = set()
    for ev in events:
        if not event_matches_mover_window(ev, window, cutoff_iso):
            continue
        hl = ev.get("headline", "")
        if hl in seen_headlines:
            continue
        seen_headlines.add(hl)
        if is_mock_event(ev):
            continue
        if filter_low_signal and _is_event_low_signal(ev):
            continue
        # Scrub absurd returns AND suppress cross-contaminated rows
        # once per event so the mover qualification, support-ratio
        # calculation, and emitted ticker list all see the same
        # cleaned data.
        raw_tickers = ev.get("market_tickers", []) or []
        clean_tickers = _suppress_duplicate_tickers(
            _scrub_implausible_ticker_returns(raw_tickers)
        )
        with_return = [t for t in clean_tickers if t.get("return_5d") is not None]
        if not with_return:
            continue
        with_dir = [t for t in clean_tickers if t.get("direction_tag") is not None]
        supporting = [
            t for t in with_dir if "supports" in (t.get("direction_tag") or "")
        ]
        support_ratio = len(supporting) / len(with_dir) if with_dir else 0.0
        scored.append(build_mover_summary(ev, with_return, support_ratio))

    scored.sort(key=lambda x: x["impact"], reverse=True)
    return scored


def _compute_market_movers_slice(
    events: list[dict],
    cutoff_iso: str,
    threshold: float,
    build_mover_summary: Callable[[dict, list[dict], float], dict],
    compute_support_ratio: Callable[[list[dict]], float],
) -> list[dict]:
    """Threshold-gated /market-movers slice over the 48h window.

    Mirrors the legacy ``api._score_event`` contract: each qualifying event
    needs at least one ticker with ``|return_5d| >= threshold`` (default 1.5%),
    and the card is built from ONLY those big-move tickers — not every
    ticker with a return.  That distinction is what separates /market-movers
    from the weekly / yearly time slices, and it's preserved here.
    """
    from market_check import (
        _suppress_duplicate_tickers,
        _scrub_implausible_ticker_returns,
    )

    scored: list[dict] = []
    seen_headlines: set[str] = set()
    for ev in events:
        if not event_matches_mover_window(ev, "market", cutoff_iso):
            continue
        hl = ev.get("headline", "") or ""
        if hl in seen_headlines:
            continue
        seen_headlines.add(hl)
        if is_mock_event(ev):
            continue
        raw_tickers = ev.get("market_tickers", []) or []
        clean_tickers = _suppress_duplicate_tickers(
            _scrub_implausible_ticker_returns(raw_tickers)
        )
        if not clean_tickers:
            continue
        big_moves = [
            t for t in clean_tickers
            if t.get("return_5d") is not None
            and abs(t["return_5d"]) >= threshold
        ]
        if not big_moves:
            continue
        # Use the single-source-of-truth support-ratio helper so this slice
        # agrees with _score_event / movers_today / persistent.  Pass the
        # CLEAN tickers (not just big_moves) so the denominator reflects
        # every verdict-carrying ticker on the event — identical semantics
        # to the legacy /market-movers bespoke path.
        support_ratio = compute_support_ratio(clean_tickers)
        scored.append(build_mover_summary(ev, big_moves, support_ratio))

    scored.sort(key=lambda x: x["impact"], reverse=True)
    return scored


def _diagnostic_summary(diag: dict[str, Any]) -> str:
    rejected = diag.get("rejections") or {}
    eligible = diag.get("eligible_events", 0)
    if eligible:
        return "Eligible mover rows were found before response-level limits."
    if not diag.get("events_scanned") and not diag.get("candidate_cards"):
        return "No analyzed events were available to evaluate."
    if rejected:
        ranked = dict(rejected)
        if diag.get("window_events"):
            ranked.pop("outside_window", None)
        meaningful = {
            k: v for k, v in ranked.items()
            if k not in ("duplicate_headline",)
        }
        if meaningful:
            ranked = meaningful
        reason, count = max(ranked.items(), key=lambda item: item[1])
        return f"No surfaced movers; largest rejection bucket is {reason} ({count})."
    return "No surfaced movers after applying the window eligibility gates."


def _time_slice_cutoff(slice_name: str, now_dt: datetime) -> tuple[str, str]:
    if slice_name == "today":
        return "today", (now_dt - timedelta(hours=24)).isoformat(timespec="seconds")
    if slice_name == "market_movers":
        return "market", (
            now_dt - timedelta(hours=_MARKET_MOVERS_WINDOW_HOURS)
        ).isoformat(timespec="seconds")
    if slice_name == "weekly":
        return "weekly", (now_dt - timedelta(days=7)).isoformat(timespec="seconds")
    if slice_name == "yearly":
        return "yearly", (now_dt - timedelta(days=365)).isoformat(timespec="seconds")
    raise ValueError(f"Unsupported time-slice diagnostics: {slice_name!r}")


def diagnose_time_slice(
    slice_name: str,
    events: list[dict],
    *,
    now: Optional[datetime] = None,
    filter_low_signal: bool = False,
    mover_threshold: Optional[float] = None,
) -> dict[str, Any]:
    """Explain why a time-window mover slice is empty.

    The diagnostic pass mirrors the production gates, but only emits
    counts.  It never fabricates mover rows or fetches market data.
    """
    from market_check import (
        _suppress_duplicate_tickers,
        _scrub_implausible_ticker_returns,
    )

    now_dt = now or datetime.now()
    window, cutoff_iso = _time_slice_cutoff(slice_name, now_dt)
    rejected: dict[str, int] = {}
    diag: dict[str, Any] = {
        "window": window,
        "cutoff": cutoff_iso,
        "events_scanned": len(events or []),
        "window_events": 0,
        "window_events_with_raw_tickers": 0,
        "window_events_with_raw_return_5d": 0,
        # Separate counters for return_1d so operators can see at a glance
        # whether the slice has fresh-event coverage even when return_5d
        # hasn't matured yet.  ``raw_usable_return`` is the union (5d OR
        # 1d) — the metric the today-window surface actually gates on.
        "window_events_with_raw_return_1d": 0,
        "window_events_with_raw_usable_return": 0,
        "events_with_tickers": 0,
        "events_with_return_5d": 0,
        "events_with_return_1d": 0,
        "events_with_usable_return": 0,
        "eligible_events": 0,
        "rejections": rejected,
    }
    # The today-window surface (``api.movers_today`` →
    # ``_today_window_qualify``) accepts ``return_1d`` as a fallback when
    # ``return_5d`` is None.  Mirror that in the diagnostic so a fresh
    # event with only a 1-day reaction reads as eligible (and isn't
    # falsely bucketed as ``no_return_5d``).  Other slices keep the
    # strict ``return_5d`` gate their surfaces actually use.
    accept_return_1d = window == "today"

    seen_headlines: set[str] = set()
    for ev in events or []:
        if not isinstance(ev, dict):
            _inc(rejected, "malformed_event")
            continue
        if not event_matches_mover_window(ev, window, cutoff_iso):
            _inc(rejected, "outside_window")
            # Today-window breakdown: report which date field excluded the
            # row so operators can tell stale ``timestamp`` (the bug
            # backfill-refreshed rows used to hit) apart from stale
            # ``last_market_check_at`` or missing fields.  Other windows
            # only consult ``timestamp`` so a per-field split would be
            # noise.
            if window == "today":
                _, reason = _today_window_match_reason(ev, cutoff_iso)
                if reason:
                    breakdown = diag.setdefault("outside_window_breakdown", {})
                    breakdown[reason] = breakdown.get(reason, 0) + 1
            continue
        diag["window_events"] += 1

        hl = ev.get("headline", "") or ""
        if hl in seen_headlines:
            _inc(rejected, "duplicate_headline")
            continue
        seen_headlines.add(hl)

        raw_tickers = ev.get("market_tickers", []) or []
        if raw_tickers:
            diag["window_events_with_raw_tickers"] += 1
            clean_for_raw_count = _suppress_duplicate_tickers(
                _scrub_implausible_ticker_returns(raw_tickers)
            )
            has_raw_r5 = any(
                isinstance(t, dict) and t.get("return_5d") is not None
                for t in clean_for_raw_count
            )
            has_raw_r1 = any(
                isinstance(t, dict) and t.get("return_1d") is not None
                for t in clean_for_raw_count
            )
            if has_raw_r5:
                diag["window_events_with_raw_return_5d"] += 1
            if has_raw_r1:
                diag["window_events_with_raw_return_1d"] += 1
            if has_raw_r5 or has_raw_r1:
                diag["window_events_with_raw_usable_return"] += 1

        if is_mock_event(ev):
            _inc(rejected, "mock_event")
            continue
        if filter_low_signal:
            reason = event_low_signal_reason(ev)
            if reason is not None:
                _inc(rejected, reason)
                continue

        if raw_tickers:
            diag["events_with_tickers"] += 1
        else:
            _inc(rejected, "no_market_tickers")
            continue

        clean_tickers = _suppress_duplicate_tickers(
            _scrub_implausible_ticker_returns(raw_tickers)
        )
        if not clean_tickers:
            _inc(rejected, "tickers_suppressed_or_invalid")
            continue

        with_return_5d = [
            t for t in clean_tickers
            if isinstance(t, dict) and t.get("return_5d") is not None
        ]
        with_return_1d = [
            t for t in clean_tickers
            if isinstance(t, dict) and t.get("return_1d") is not None
        ]
        with_usable_return = [
            t for t in clean_tickers
            if isinstance(t, dict)
            and (t.get("return_5d") is not None or t.get("return_1d") is not None)
        ]
        if with_return_5d:
            diag["events_with_return_5d"] += 1
        if with_return_1d:
            diag["events_with_return_1d"] += 1
        if with_usable_return:
            diag["events_with_usable_return"] += 1

        qualifying = with_usable_return if accept_return_1d else with_return_5d
        if not qualifying:
            # ``no_usable_return`` for today (covers both null windows);
            # ``no_return_5d`` for slices whose surface still requires it.
            _inc(
                rejected,
                "no_usable_return" if accept_return_1d else "no_return_5d",
            )
            continue

        if mover_threshold is not None:
            big_moves = [
                t for t in qualifying
                if abs(t.get("return_5d") or 0.0) >= mover_threshold
            ]
            if not big_moves:
                _inc(rejected, "below_mover_threshold")
                continue

        diag["eligible_events"] += 1

    diag["summary"] = _diagnostic_summary(diag)
    return diag


def _persistent_card_rejection_reason(card: dict) -> str:
    if not isinstance(card, dict):
        return "malformed_card"
    if card.get("low_information") is True:
        return "low_information"
    thesis = card.get("thesis_state")
    if thesis in ("low_information", "falsified"):
        return str(thesis)
    if card.get("stale_signal") in ("stale", "legacy"):
        return str(card.get("stale_signal"))
    weighted = card.get("weighted_evidence")
    label = weighted.get("evidence_label") if isinstance(weighted, dict) else None
    if label != "supportive":
        return "not_supportive_evidence"
    if thesis not in ("confirming", "partial"):
        return "not_thesis_relevant"
    conviction = card.get("conviction")
    if not isinstance(conviction, dict):
        return "missing_conviction"
    if conviction.get("conviction_class") != "conviction":
        return "not_conviction_class"
    if conviction.get("impact_level") != "high":
        return "not_high_impact"
    # Sector-ETF-as-primary gate — kept after the conviction / impact
    # checks so its order matches ``is_high_conviction_persistent``.
    # Lazy import: the normalizer is a sibling module the route layer
    # already pairs with this one, but keeping the import inside the
    # function avoids any module-load coupling.
    from mover_card_normalizer import primary_is_sector_etf
    if primary_is_sector_etf(card):
        return "sector_etf_as_primary"
    return "filtered_by_persistent_gate"


def diagnose_persistent_cards(
    raw_cards: list[dict] | None,
    eligible_cards: list[dict] | None,
) -> dict[str, Any]:
    """Explain persistent high-impact gate fallout without changing rows."""
    raw = raw_cards if isinstance(raw_cards, list) else []
    eligible = eligible_cards if isinstance(eligible_cards, list) else []
    eligible_ids = {
        c.get("event_id") if isinstance(c, dict) else None
        for c in eligible
    }
    rejected: dict[str, int] = {}
    for card in raw:
        if not isinstance(card, dict):
            _inc(rejected, "malformed_card")
            continue
        if card.get("event_id") in eligible_ids:
            continue
        _inc(rejected, _persistent_card_rejection_reason(card))

    diag: dict[str, Any] = {
        "window": "persistent",
        "candidate_cards": len(raw),
        "eligible_events": len(eligible),
        "rejections": rejected,
    }
    diag["summary"] = _diagnostic_summary(diag)
    return diag


def _compute_persistent_slice(
    events: list[dict],
    now_dt: datetime,
    build_persistent_summary: Callable[[dict, list[dict], datetime], dict],
    classify_decay_fn: Callable[..., dict],
) -> list[dict]:
    """Persistent-movers slice.  Mirrors the legacy inline path in api.py.

    Phase 1: strict — events > 7d old where at least one ticker still
             reads Accelerating / Holding.
    Phase 2: fallback — if strict is short, supplement with any event
             carrying a confirmed ticker move, with non-Accelerating /
             Holding trajectories relabelled as "Monitoring".

    Both phases now feed a single response payload that the
    ``/movers/persistent`` route filters through
    ``is_high_conviction_persistent``.  Fallback rows do not bypass the
    gate — they're simply candidates for it — so the route can come
    back empty when no candidate clears the high-conviction bar.
    """
    from market_check import (
        _suppress_duplicate_tickers,
        _scrub_implausible_ticker_returns,
    )
    cutoff_recent = (now_dt - timedelta(days=7)).isoformat(timespec="seconds")
    unique_events = _dedupe_by_headline(events)

    def _clean(ev: dict) -> list[dict]:
        return _suppress_duplicate_tickers(
            _scrub_implausible_ticker_returns(
                ev.get("market_tickers", []) or []
            )
        )

    _MIN_PERSISTENT = 4  # Supplement with fallback until we have at least this many

    strict: list[dict] = []
    strict_ids: set[int] = set()
    for ev in unique_events:
        if is_mock_event(ev):
            continue
        if _has_no_mechanism(ev):
            continue
        ts = ev.get("timestamp", "") or ""
        if ts >= cutoff_recent:
            continue
        clean_tickers = _clean(ev)
        with_return = [t for t in clean_tickers if t.get("return_5d") is not None]
        if not with_return:
            continue
        has_persistent = any(
            classify_decay_fn(t.get("return_5d"), t.get("return_20d"))["label"]
            in ("Accelerating", "Holding")
            for t in with_return
        )
        if not has_persistent:
            continue
        strict.append(build_persistent_summary(ev, with_return, now_dt))
        strict_ids.add(ev.get("id", 0))

    strict.sort(key=lambda x: (-x["days_since_event"], -x["impact"]))

    if len(strict) >= _MIN_PERSISTENT:
        return strict

    # Phase 2 fallback: supplement with any mover that has a confirmed
    # ticker move, up to _MIN_PERSISTENT total.  Non-persistent
    # trajectories are relabelled "Monitoring".
    fallback: list[dict] = []
    for ev in unique_events:
        if ev.get("id", 0) in strict_ids:
            continue
        if is_mock_event(ev):
            continue
        if _has_no_mechanism(ev):
            continue
        clean_tickers = _clean(ev)
        with_return = [t for t in clean_tickers if t.get("return_5d") is not None]
        if not with_return:
            continue
        summary = build_persistent_summary(ev, with_return, now_dt)
        for t in summary["tickers"]:
            if t.get("decay") in ("Unknown", "Fading", "Reversed", None):
                t["decay"] = "Monitoring"
                t["decay_evidence"] = "Trajectory not yet classified"
        fallback.append(summary)

    fallback.sort(key=lambda x: -x["impact"])
    return strict + fallback


# ---------------------------------------------------------------------------
# Public API: compute + get_slice
# ---------------------------------------------------------------------------


def compute_slice(
    slice_name: str,
    events: list[dict],
    *,
    now: Optional[datetime] = None,
    build_mover_summary: Optional[Callable[[dict, list[dict], float], dict]] = None,
    build_persistent_summary: Optional[Callable[[dict, list[dict], datetime], dict]] = None,
    classify_decay_fn: Optional[Callable[..., dict]] = None,
    compute_support_ratio_fn: Optional[Callable[[list[dict]], float]] = None,
    mover_threshold: Optional[float] = None,
) -> list[dict]:
    """Pure computation of a named slice from a pre-loaded events list.

    ``build_mover_summary`` and ``build_persistent_summary`` are the
    shape-matching helpers from ``api.py`` (imported lazily inside
    ``get_slice`` but overridable here for tests).  Keeping them
    injectable means this module never imports api.py — the only
    outbound dependency is ``db`` for persistence and ``market_check``
    for ``classify_decay``.
    """
    now_dt = now or datetime.now()

    # Lazy defaults.  We import these inside the function so tests
    # that want to hand in stubs don't pay the import cost.
    if build_mover_summary is None or build_persistent_summary is None:
        from api import (
            _build_mover_summary as _default_build,
            _persistent_summary as _default_persistent,
        )
        if build_mover_summary is None:
            build_mover_summary = _default_build
        if build_persistent_summary is None:
            build_persistent_summary = _default_persistent
    if classify_decay_fn is None:
        from market_check import classify_decay
        classify_decay_fn = classify_decay
    if compute_support_ratio_fn is None:
        from api import _compute_support_ratio
        compute_support_ratio_fn = _compute_support_ratio
    if mover_threshold is None:
        from api import _MOVER_THRESHOLD
        mover_threshold = _MOVER_THRESHOLD

    if slice_name == "market_movers":
        cutoff = (
            now_dt - timedelta(hours=_MARKET_MOVERS_WINDOW_HOURS)
        ).isoformat(timespec="seconds")
        return _compute_market_movers_slice(
            events, cutoff, mover_threshold,
            build_mover_summary, compute_support_ratio_fn,
        )
    if slice_name == "weekly":
        cutoff = (now_dt - timedelta(days=7)).isoformat(timespec="seconds")
        return _compute_time_slice(events, cutoff, build_mover_summary,
                                   window="weekly",
                                   filter_low_signal=True)
    if slice_name == "yearly":
        cutoff = (now_dt - timedelta(days=365)).isoformat(timespec="seconds")
        return _compute_time_slice(events, cutoff, build_mover_summary,
                                   window="yearly")
    if slice_name == "persistent":
        return _compute_persistent_slice(
            events, now_dt, build_persistent_summary, classify_decay_fn,
        )
    raise ValueError(f"Unknown mover slice: {slice_name!r}")


def get_slice(
    slice_name: str,
    *,
    limit: int,
    ttl_seconds: Optional[int] = None,
    force: bool = False,
    allow_refresh: bool = True,
    now: Optional[datetime] = None,
    load_events_fn: Optional[Callable[[int], list[dict]]] = None,
    load_cache_fn: Optional[Callable[[str], Optional[dict]]] = None,
    save_cache_fn: Optional[Callable[..., None]] = None,
    fingerprint_fn: Optional[Callable[[], tuple[int, int]]] = None,
    compute_fn: Optional[Callable[..., list[dict]]] = None,
) -> list[dict]:
    """Read a mover slice from the persisted cache, refreshing if stale.

    Staleness rules:
      1. ``force=True`` bypasses the cache entirely.
      2. No cached row at all → bootstrap: compute and persist.
      3. Cached row older than ``ttl_seconds`` → recompute and persist.
      4. ``(event_count, max_event_id)`` has changed since the cached
         row was built → recompute and persist.  This catches new
         events that were saved inside the TTL window so the UI
         reflects them immediately.
      5. Otherwise → serve the cached payload directly.

    ``allow_refresh=False`` makes the read STRICTLY read-only: the
    cached payload is served (trimmed to ``limit``) when a row exists,
    else an empty list is returned — the cache is NEVER recomputed or
    persisted, and staleness / fingerprint / version are ignored in
    favour of a guaranteed no-write read.  This is the contract the
    event-detail ``mover_context`` block uses so ``GET /events/{id}``
    never writes the DB (see routes/events.py / routes/movers.py);
    the ``/movers/*`` endpoints keep the default lazy-refresh behaviour.

    The callables are injectable so tests can observe the underlying
    call count without patching module globals, and so rare bootstrap
    paths (tools scripts, one-shot recomputes) can hand in fakes.
    """
    # Lazy defaults — resolve from db / api on first use.
    if load_events_fn is None:
        from db import load_recent_events
        load_events_fn = load_recent_events
    if load_cache_fn is None:
        from db import load_movers_cache
        load_cache_fn = load_movers_cache
    if save_cache_fn is None:
        from db import save_movers_cache
        save_cache_fn = save_movers_cache
    if fingerprint_fn is None:
        from db import get_events_fingerprint
        fingerprint_fn = get_events_fingerprint
    if compute_fn is None:
        compute_fn = compute_slice

    ttl = ttl_seconds if ttl_seconds is not None else _DEFAULT_TTLS.get(slice_name, 1800)
    now_dt = now or datetime.now()

    # 0. Read-only mode — never recompute or persist.  Serve the cached
    # payload (trimmed) when present, else []; ignore staleness.  Keeps
    # read endpoints (event-detail mover_context) from writing the DB.
    if not allow_refresh:
        cached = load_cache_fn(slice_name)
        if cached is None:
            return []
        return (cached.get("payload") or [])[:limit]

    # 1. Forced refresh — always recompute.
    if force:
        return _recompute_and_persist(
            slice_name, limit, now_dt,
            load_events_fn, save_cache_fn, fingerprint_fn, compute_fn,
        )

    cached = load_cache_fn(slice_name)
    fp_count, fp_max = fingerprint_fn()

    if cached is None:
        # 2. Bootstrap: no row yet.
        return _recompute_and_persist(
            slice_name, limit, now_dt,
            load_events_fn, save_cache_fn, fingerprint_fn, compute_fn,
        )

    # 3. TTL check — compare built_at to now.
    try:
        built_at = datetime.fromisoformat(cached["built_at"])
    except (ValueError, TypeError, KeyError):
        built_at = None

    if built_at is None or (now_dt - built_at).total_seconds() > ttl:
        return _recompute_and_persist(
            slice_name, limit, now_dt,
            load_events_fn, save_cache_fn, fingerprint_fn, compute_fn,
        )

    # 4. Fingerprint check — new events saved since the cache was built.
    if (cached["event_count"] != fp_count
            or cached["max_event_id"] != fp_max):
        return _recompute_and_persist(
            slice_name, limit, now_dt,
            load_events_fn, save_cache_fn, fingerprint_fn, compute_fn,
        )

    # 4b. Version check — compute logic changed since the cache was built.
    if cached.get("compute_version") != _COMPUTE_VERSION:
        return _recompute_and_persist(
            slice_name, limit, now_dt,
            load_events_fn, save_cache_fn, fingerprint_fn, compute_fn,
        )

    # 5. Hit — trim to limit and return.
    payload = cached.get("payload") or []
    return payload[:limit]


def _recompute_and_persist(
    slice_name: str,
    limit: int,
    now_dt: datetime,
    load_events_fn: Callable[[int], list[dict]],
    save_cache_fn: Callable[..., None],
    fingerprint_fn: Callable[[], tuple[int, int]],
    compute_fn: Callable[..., list[dict]],
) -> list[dict]:
    """Rebuild a slice from raw events and write it through to SQLite.

    We persist the *unlimited* payload so callers asking for different
    ``limit`` values all hit the same cached row.  The DB write is
    wrapped in a try so a transient failure (disk full, lock) degrades
    into a successful request — the caller still gets the fresh data.
    """
    events = load_events_fn(500)
    try:
        payload = compute_fn(slice_name, events, now=now_dt)
    except Exception:
        _log.warning(
            "movers_cache: compute failed for slice=%s", slice_name,
            exc_info=True,
        )
        return []

    fp_count, fp_max = fingerprint_fn()
    built_at = now_dt.replace(microsecond=0).isoformat()

    try:
        save_cache_fn(slice_name, payload, built_at, fp_count, fp_max,
                      compute_version=_COMPUTE_VERSION)
    except Exception:
        _log.warning(
            "movers_cache: save failed for slice=%s", slice_name,
            exc_info=True,
        )

    return payload[:limit]


def invalidate(slice_name: Optional[str] = None) -> None:
    """Drop all cached slices, or one named slice.

    Called from the analyse path after a new event is saved so the
    next read rebuilds.  Cheap enough to be unconditional; the next
    request pays the recompute once.
    """
    try:
        from db import clear_movers_cache
        clear_movers_cache(slice_name)
    except Exception:
        _log.warning(
            "movers_cache: invalidate failed", exc_info=True,
        )
