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
    "weekly":     3600,   # 60 min — validated in movers_cache_validation.py
    "yearly":     7200,   # 120 min — rolls slowly, low cost to keep warm
    "persistent": 3600,   # 60 min — same target as weekly
}


# ---------------------------------------------------------------------------
# Slice definitions — each one knows how to filter + sort the event list.
# ---------------------------------------------------------------------------


def _is_mover_event(ev: dict) -> list[dict]:
    """Return the list of tickers on ``ev`` that have non-null 5d returns.

    Empty list means the event does not qualify as a mover at all.
    """
    tickers = ev.get("market_tickers", []) or []
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


def _compute_time_slice(
    events: list[dict],
    cutoff_iso: str,
    build_mover_summary: Callable[[dict, list[dict], float], dict],
) -> list[dict]:
    """Shared logic for the weekly + yearly slices.

    Mirrors the legacy ``_build_time_movers`` inline helper in api.py.
    Events newer than ``cutoff_iso``, deduplicated by headline, any
    ticker with ``return_5d`` qualifies, sorted by impact descending.
    """
    scored: list[dict] = []
    seen_headlines: set[str] = set()
    for ev in events:
        ts = ev.get("timestamp", "") or ""
        if ts < cutoff_iso:
            continue
        hl = ev.get("headline", "")
        if hl in seen_headlines:
            continue
        seen_headlines.add(hl)
        with_return = _is_mover_event(ev)
        if not with_return:
            continue
        with_dir = [
            t for t in ev.get("market_tickers", []) or []
            if t.get("direction_tag") is not None
        ]
        supporting = [
            t for t in with_dir if "supports" in (t.get("direction_tag") or "")
        ]
        support_ratio = len(supporting) / len(with_dir) if with_dir else 0.0
        scored.append(build_mover_summary(ev, with_return, support_ratio))

    scored.sort(key=lambda x: x["impact"], reverse=True)
    return scored


def _compute_persistent_slice(
    events: list[dict],
    now_dt: datetime,
    build_persistent_summary: Callable[[dict, list[dict], datetime], dict],
    classify_decay_fn: Callable[..., dict],
) -> list[dict]:
    """Persistent-movers slice.  Mirrors the legacy inline path in api.py.

    Phase 1: strict — events > 7d old where at least one ticker still
             reads Accelerating / Holding.
    Phase 2: fallback — if strict is empty, every event with a
             confirmed ticker move, with non-Accelerating/Holding
             trajectories relabelled as "Monitoring".  The hero section
             is never allowed to come back empty.
    """
    cutoff_recent = (now_dt - timedelta(days=7)).isoformat(timespec="seconds")
    unique_events = _dedupe_by_headline(events)

    strict: list[dict] = []
    for ev in unique_events:
        ts = ev.get("timestamp", "") or ""
        if ts >= cutoff_recent:
            continue
        with_return = _is_mover_event(ev)
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

    if strict:
        strict.sort(key=lambda x: (-x["days_since_event"], -x["impact"]))
        return strict

    # Phase 2 fallback: any mover at all, tagged Monitoring where we
    # don't have a clean trajectory classification.
    fallback: list[dict] = []
    for ev in unique_events:
        with_return = _is_mover_event(ev)
        if not with_return:
            continue
        summary = build_persistent_summary(ev, with_return, now_dt)
        for t in summary["tickers"]:
            if t.get("decay") in ("Unknown", "Fading", "Reversed", None):
                t["decay"] = "Monitoring"
                t["decay_evidence"] = "Trajectory not yet classified"
        fallback.append(summary)

    fallback.sort(key=lambda x: -x["impact"])
    return fallback


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

    if slice_name == "weekly":
        cutoff = (now_dt - timedelta(days=7)).isoformat(timespec="seconds")
        return _compute_time_slice(events, cutoff, build_mover_summary)
    if slice_name == "yearly":
        cutoff = (now_dt - timedelta(days=365)).isoformat(timespec="seconds")
        return _compute_time_slice(events, cutoff, build_mover_summary)
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
        save_cache_fn(slice_name, payload, built_at, fp_count, fp_max)
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
