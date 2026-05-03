"""
auto_revisit.py

Automated revisit-snapshot collector.

Mirrors ``market_snapshots``: a lightweight daemon thread, env-gated so test
suites + local dev don't spin it up by accident, that periodically sweeps
saved events and captures the revisit snapshots that are due.

What "due" means
----------------
Each saved event has an ``event_date``.  Calendar age past that date hits
an anchor at 1d, 5d, and 20d.  When an event's age >= anchor AND no
snapshot for that anchor has been stored yet, it's due.  A small grace
window catches events we missed (loop didn't fire on the exact day).

Capture path
------------
For each (event_id, day) pair, the scheduler calls
``market_check.followup_check`` + ``db.append_revisit_snapshot`` — the
same primitives the manual ``POST /events/{id}/revisit`` route already
uses, so no new DB shape and no new provider boundary.

Lifecycle
---------
Opt-in via ``AUTO_REVISIT_ENABLED=true`` (matches the ``MARKET_SNAPSHOTS_ENABLED``
pattern).  ``AUTO_REVISIT_INTERVAL`` overrides the default 1-hour loop
cadence.  Starts in the FastAPI lifespan alongside market_snapshots.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from typing import Callable, Optional

_log = logging.getLogger("second_order.auto_revisit")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Revisit anchors the auto-scheduler collects.  Narrower than the full
# ``api._REVISIT_DAYS`` (1, 5, 20, 60) because the task scopes auto-capture
# to the three windows a macro desk actually watches day-to-day.  The 60d
# snapshot stays manual — by the time it's due, desk review is the right
# trigger, not a refresh loop.
REVISIT_ANCHORS: tuple[int, ...] = (1, 5, 20)

# How many calendar days past an anchor the scheduler will still try to
# capture.  Scheduler is a catch-up mechanism: when offline for a stretch,
# it should recover every missed anchor on boot.  ``followup_check``
# computes returns from the price cache, so a 1d anchor captured today on
# a week-old event still produces the correct 1d return — we're just
# recording it late.  Dedup via _existing_days prevents re-capture.  The
# cap exists only to bound the scan: events older than anchor + grace are
# archive material, handled by the manual revisit route.
ANCHOR_GRACE_DAYS: int = 30

# Seconds between refresh-loop iterations.  1h is more than enough given
# anchor granularity is days; a missed tick is caught by ``ANCHOR_GRACE_DAYS``.
DEFAULT_REFRESH_INTERVAL: int = 3600


# ---------------------------------------------------------------------------
# Due-detection helpers
# ---------------------------------------------------------------------------


def _days_since(event_date: Optional[str], now: datetime) -> Optional[int]:
    """Calendar days between ``event_date`` (YYYY-MM-DD) and ``now``.

    Returns None when the date is missing or unparseable — the caller
    treats that as "don't consider this event for auto capture".
    """
    if not event_date or not isinstance(event_date, str):
        return None
    try:
        d = datetime.strptime(event_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    return (now.date() - d).days


def _existing_days(event: dict) -> set[int]:
    """Return the set of revisit days already captured on this event.

    Tolerates both decoded (list) and raw-JSON-string ``revisit_snapshots``
    values so this module doesn't depend on whether the event was loaded
    through ``_decode_event_row`` or hit a rawer read path.
    """
    snaps = event.get("revisit_snapshots") or []
    if isinstance(snaps, str):
        try:
            snaps = json.loads(snaps)
        except (json.JSONDecodeError, TypeError):
            return set()
    if not isinstance(snaps, list):
        return set()
    out: set[int] = set()
    for s in snaps:
        if isinstance(s, dict):
            day = s.get("day")
            if isinstance(day, int):
                out.add(day)
    return out


def find_due_events(
    events: list[dict],
    now: Optional[datetime] = None,
    anchors: tuple[int, ...] = REVISIT_ANCHORS,
    grace_days: int = ANCHOR_GRACE_DAYS,
) -> list[tuple[int, int]]:
    """Return ``[(event_id, due_day), ...]`` pairs ready for capture.

    An event is due for ``anchor`` when:
      * its calendar age >= anchor
      * its calendar age <= anchor + grace_days (late-boot safety window)
      * no snapshot for that anchor is already on the event row
      * the event has an ``event_date`` AND at least one stored ticker

    Output is ordered newest-event-first within each anchor so the
    scheduler prioritises the freshest data.
    """
    if now is None:
        now = datetime.now()

    due: list[tuple[int, int]] = []
    for ev in events:
        eid = ev.get("id")
        if not isinstance(eid, int):
            continue
        age = _days_since(ev.get("event_date"), now)
        if age is None:
            continue
        tickers = ev.get("market_tickers") or []
        if not tickers:
            continue
        captured = _existing_days(ev)
        for day in anchors:
            if age < day:
                continue
            if age - day > grace_days:
                continue
            if day in captured:
                continue
            due.append((eid, day))
    return due


# ---------------------------------------------------------------------------
# Capture pass
# ---------------------------------------------------------------------------


def _build_day_snapshot(day: int, outcomes: list[dict], now_iso: str) -> dict:
    """Build the day-scoped snapshot payload ``append_revisit_snapshot`` wants.

    Mirrors the shape assembled in ``routes.events.capture_revisit_snapshot``
    so consumers of ``load_revisit_snapshots`` see the same dict regardless
    of whether the capture came from the manual route or the scheduler.
    """
    return_key = f"return_{day}d"
    day_tickers = [
        {
            "symbol":    o["symbol"],
            "role":      o.get("role", "beneficiary"),
            return_key:  o[return_key],
            "direction": o.get("direction"),
        }
        for o in outcomes
        if isinstance(o, dict) and o.get(return_key) is not None
    ]
    return {
        "day":         day,
        "captured_at": now_iso,
        "tickers":     day_tickers,
    }


def capture_due_snapshots(
    now: Optional[datetime] = None,
    load_events_fn: Optional[Callable[[int], list[dict]]] = None,
    load_event_fn: Optional[Callable[[int], Optional[dict]]] = None,
    followup_check_fn: Optional[Callable[..., list[dict]]] = None,
    append_fn: Optional[Callable[[int, dict], bool]] = None,
    anchors: tuple[int, ...] = REVISIT_ANCHORS,
    grace_days: int = ANCHOR_GRACE_DAYS,
) -> list[dict]:
    """Run one pass: find due events + capture.  Returns a capture log.

    Each log entry is a dict:
        {event_id, day, status, error?}
    where ``status`` is one of:
        "captured"      — snapshot written
        "no_data"       — followup_check returned no bars for this anchor
        "event_missing" — event_id vanished between discovery and capture
        "error"         — followup_check / append raised

    The callables are injectable so tests can hand in stubs without
    patching module globals.  In production all of them default to the
    shared db / market_check helpers.
    """
    # Lazy default wiring so import-time side effects stay zero.
    if load_events_fn is None:
        from db import load_recent_events
        load_events_fn = load_recent_events
    if load_event_fn is None:
        from db import load_event_by_id
        load_event_fn = load_event_by_id
    if followup_check_fn is None:
        from market_check import followup_check
        followup_check_fn = followup_check
    if append_fn is None:
        from db import append_revisit_snapshot
        append_fn = append_revisit_snapshot

    if now is None:
        now = datetime.now()

    # 500 events ≈ 30-90 days at typical save rates — ample for the 20d anchor.
    events = load_events_fn(500)
    due = find_due_events(events, now=now, anchors=anchors, grace_days=grace_days)

    if not due:
        return []

    now_iso = now.isoformat(timespec="seconds")

    # Group by event_id so one followup_check call covers every due anchor
    # on the same event — avoids N provider calls for an event with 1d + 5d
    # both due (common when the scheduler has been offline a few days).
    by_event: dict[int, list[int]] = {}
    for eid, day in due:
        by_event.setdefault(eid, []).append(day)

    log: list[dict] = []
    for eid, days in by_event.items():
        # Re-load the event to make sure we have the latest snapshot list
        # (guards against a manual capture landing between discovery and
        # our write; append_fn also dedupes by day, this just saves work).
        target = load_event_fn(eid)
        if target is None:
            for day in days:
                log.append({"event_id": eid, "day": day, "status": "event_missing"})
            continue

        already = _existing_days(target)
        remaining = [d for d in days if d not in already]
        if not remaining:
            continue

        event_date = target.get("event_date") or (target.get("timestamp") or "")[:10]
        tickers = target.get("market_tickers") or []
        if not event_date or not tickers:
            for day in remaining:
                log.append({"event_id": eid, "day": day, "status": "no_data"})
            continue

        try:
            outcomes = followup_check_fn(tickers, event_date)
        except Exception as exc:
            _log.warning("auto_revisit: followup_check failed for event %d",
                         eid, exc_info=True)
            for day in remaining:
                log.append({
                    "event_id": eid, "day": day,
                    "status": "error", "error": str(exc),
                })
            continue

        for day in remaining:
            snapshot = _build_day_snapshot(day, outcomes, now_iso)
            if not snapshot["tickers"]:
                # No outcomes carry return_{day}d yet — data just isn't
                # ready for this anchor.  The loop will re-check on the
                # next tick.
                log.append({"event_id": eid, "day": day, "status": "no_data"})
                continue
            try:
                ok = append_fn(eid, snapshot)
            except Exception as exc:
                _log.warning("auto_revisit: append failed for event %d day %d",
                             eid, day, exc_info=True)
                log.append({
                    "event_id": eid, "day": day,
                    "status": "error", "error": str(exc),
                })
                continue
            log.append({
                "event_id": eid, "day": day,
                "status": "captured" if ok else "event_missing",
            })

    if log:
        captured = sum(1 for e in log if e["status"] == "captured")
        _log.info("auto_revisit: pass complete — %d/%d captured", captured, len(log))
    return log


# ---------------------------------------------------------------------------
# Background thread lifecycle — mirrors market_snapshots.py
# ---------------------------------------------------------------------------

_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_thread_lock = threading.Lock()


def is_running() -> bool:
    """Return True if the auto-revisit refresh thread is currently running."""
    with _thread_lock:
        return _thread is not None and _thread.is_alive()


def start_background_refresh(interval: int = DEFAULT_REFRESH_INTERVAL) -> bool:
    """Start the daemon capture thread.

    Returns True when a new thread was started, False when one was
    already running.  Idempotent so lifespan hooks can call it safely.
    """
    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return False
        _stop_event.clear()

        def _loop() -> None:
            # Capture once on startup so a process that came back online
            # after a missed anchor window catches the grace events.
            try:
                capture_due_snapshots()
            except Exception:
                _log.exception("initial auto_revisit pass failed")
            while not _stop_event.is_set():
                if _stop_event.wait(interval):
                    break
                try:
                    capture_due_snapshots()
                except Exception:
                    _log.exception("auto_revisit pass failed")

        _thread = threading.Thread(
            target=_loop, daemon=True, name="auto-revisit",
        )
        _thread.start()
        _log.info("auto_revisit background refresh started (interval=%ds)", interval)
        return True


def stop_background_refresh(timeout: float = 5.0) -> None:
    """Signal the background thread to stop and wait for it to exit."""
    global _thread
    _stop_event.set()
    with _thread_lock:
        if _thread is not None:
            _thread.join(timeout=timeout)
            _thread = None
    _log.info("auto_revisit background refresh stopped")
