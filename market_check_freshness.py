"""
market_check_freshness.py

Event-age-aware freshness layer for saved-event market checks.

Every saved event carries two independently-versioned surfaces:

  * The *analysis* (headline classification, mechanism text, tickers list) —
    captured once at analyse time, rarely rewritten.

  * The *market validation* (per-ticker returns, direction tags, notes) —
    computed against a live provider and naturally ages as bars roll in.

Previously the cached-analysis layer in ``db.find_cached_analysis`` bundled
both together under a flat 24h TTL: a cache hit returned the stored market
block verbatim, and a cache miss re-ran the full analysis including a fresh
market check.  That is wasteful for recent events (4-hour-old tickers are
fine, no need to re-analyse) and wrong for older events (yesterday's tickers
may be days stale while the analysis is still valid).

This module splits those concerns.  It owns:

  1. ``compute_staleness(...)`` — a pure function that turns an event's age
     and the age of its last market check into one of four statuses:

        fresh   — stored tickers are still good, do not refresh
        stale   — refresh threshold exceeded, caller should re-run
        frozen  — event is older than the frozen-age cutoff; treat as
                  archived unless the caller explicitly forces
        legacy  — row has no ``last_market_check_at`` yet (pre-migration);
                  behave like stale so we stamp it on first read

  2. ``refresh_market_for_saved_event(event, force=False)`` — the imperative
     layer that calls staleness, runs ``followup_check`` /
     ``market_check`` via the SQLite-cached provider path, persists the
     result through ``db.update_event_market_refresh``, and returns a
     market block ready for the API caller.

Tunable windows
---------------

The thresholds below are empirically calibrated against the live events
archive (see ``tools/market_check_freshness_validation.py``):

  * ``_EVENT_AGE_RECENT_DAYS = 7`` — events within this window are "hot";
    an intraday 4-hour rule keeps them close to real-time without
    dominating the provider budget.
  * ``_EVENT_AGE_FROZEN_DAYS = 30`` — beyond this, forward returns have
    converged and daily refreshes add no meaningful signal; we freeze
    the row unless the caller passes ``force=True``.
  * ``_REFRESH_RECENT_HOURS = 4`` — one business-day quarter; a practical
    balance between intraday tape and provider cost.
  * ``_REFRESH_OLDER_HOURS = 24`` — one trading day; the smallest
    refresh that still guarantees a fresh closing bar.

Grounded numbers (last calibration run):

    Population: 65 events (57 live archive + 8 synthetic frozen tail)
    Workload:   17 reads per event per day (8h dashboard + 1 backtest)
                = 1,105 replayed refresh decisions

                             refreshes  refresh-rate  notes
    tight   (1h /12h rule)        523         47.3%   excess provider load
    current (4h /24h rule)        176         15.9%   66% call savings vs tight
    loose   (8h /48h rule)        119         10.8%   loses intraday responsiveness
    frozen-cut 14d                174         15.7%   more aggressive archive

    Frozen reads touched:       0 / 51 across all rule sets.

The "current" row uses exactly the constants compiled below.  If any of
those numbers change, ``tools/market_check_freshness_validation.py``
must be re-run and the table above updated — the script's closing
assertion enforces that the refresh rate stays inside the validated
10%-30% band.
"""

from __future__ import annotations

import logging
from datetime import date as _date, datetime as _dt, timedelta as _timedelta
from typing import Any, Optional

import event_age_policy

_log = logging.getLogger("second_order.market_freshness")


# ---------------------------------------------------------------------------
# Tunables — DELEGATED to event_age_policy.
#
# The four names below are kept as module-level attributes so the
# existing validation script (tools/market_check_freshness_validation.py)
# can temporarily override them to replay candidate rule sets.  They
# mirror the event_age_policy tunables in every meaningful dimension:
#
#     _EVENT_AGE_RECENT_DAYS   ← event_age_policy._WARM_MAX_DAYS
#     _EVENT_AGE_FROZEN_DAYS   ← event_age_policy._STABLE_MAX_DAYS
#     _REFRESH_RECENT_HOURS    ← event_age_policy._WARM_TTL_SECONDS / 3600
#     _REFRESH_OLDER_HOURS     ← event_age_policy._STABLE_TTL_SECONDS / 3600
#
# Updating any of these requires re-running the validation script and
# the corresponding event_age_policy validation.
# ---------------------------------------------------------------------------

_EVENT_AGE_RECENT_DAYS: int = event_age_policy._WARM_MAX_DAYS
_EVENT_AGE_FROZEN_DAYS: int = event_age_policy._STABLE_MAX_DAYS
_REFRESH_RECENT_HOURS: int = event_age_policy._WARM_TTL_SECONDS // 3600
_REFRESH_OLDER_HOURS: int = event_age_policy._STABLE_TTL_SECONDS // 3600


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _parse_iso(value: Optional[str]) -> Optional[_dt]:
    """Parse an ISO-8601 timestamp or YYYY-MM-DD date.  Never raises."""
    if not value or not isinstance(value, str):
        return None
    try:
        return _dt.fromisoformat(value)
    except ValueError:
        pass
    try:
        return _dt.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


# Delegate the age-in-days calculation to the shared policy so both
# modules agree on anchor resolution (event_date → timestamp → clamp).
_event_age_days = event_age_policy.event_age_days


def _hours_since(ts: Optional[str], now: _dt) -> Optional[float]:
    """Return hours elapsed since ``ts`` or None if unparseable."""
    parsed = _parse_iso(ts)
    if parsed is None:
        return None
    delta = (now - parsed).total_seconds() / 3600.0
    return max(0.0, delta)


def _refresh_threshold_for(age_days: int) -> int:
    """Return the max hours between checks before a row is considered stale.

    Backed by the shared ``event_age_policy`` buckets.  The market-check
    layer collapses hot + warm into one "recent" decision so the existing
    calibration (4h recent / 24h older) is preserved unchanged.  A hot
    bucket row uses the same 4h window as warm rather than the policy's
    2h TTL — this keeps the market_check refresh rate calibrated at the
    old 15.9% figure and avoids doubling provider traffic on today /
    yesterday events.  Other consumers that want the tighter 2h window
    can call ``event_age_policy.classify_event_age`` directly.
    """
    # Use the module-level override values so the validation script
    # can still replay candidate tunables.
    if age_days < _EVENT_AGE_RECENT_DAYS:
        return _REFRESH_RECENT_HOURS
    return _REFRESH_OLDER_HOURS


def _has_return_data(tickers: list[dict]) -> bool:
    """True when at least one ticker row carries a populated return window.

    A row that has tickers but no numeric returns is functionally legacy:
    it was saved before a successful market_check ever ran (or the provider
    was unavailable at save time).  Treating it as legacy means the
    refresh path will populate it on first read instead of leaving it
    permanently blank just because the event is old.
    """
    for t in tickers or []:
        for k in ("return_1d", "return_5d", "return_20d"):
            if t.get(k) is not None:
                return True
    return False


# ---------------------------------------------------------------------------
# Public: staleness decision
# ---------------------------------------------------------------------------


def compute_staleness(
    event: dict,
    *,
    now: Optional[_dt] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Classify a saved event's market-check freshness.

    ``event`` must be a dict loaded from the DB with at least
    ``event_date`` / ``timestamp`` and ``last_market_check_at``.  Missing
    keys are tolerated — the event is classified as ``legacy`` and the
    caller is expected to refresh on first access so the row gets
    stamped going forward.

    ``force=True`` bypasses the frozen cutoff but still reports the
    *natural* status in ``natural_status`` so callers and tests can see
    that a force was required.

    Returns a dict with:

        status                  — "fresh" | "stale" | "frozen" | "legacy"
        natural_status          — same but always reflects the unforced view
        event_age_days          — integer >= 0
        hours_since_check       — float, or None when no prior check exists
        refresh_threshold_hours — int for recent/older, None for frozen
        reason                  — short human-readable explanation
    """
    now_dt = now or _dt.now()
    age_days = _event_age_days(event, now_dt)
    last_check = event.get("last_market_check_at")
    hours = _hours_since(last_check, now_dt)

    # A row whose tickers have no numeric returns has never really been
    # validated.  We treat that as legacy regardless of age so the first
    # read populates it.  Rows with zero tickers to begin with fall
    # through the normal rules (nothing to refresh anyway).
    stored_tickers = event.get("market_tickers") or []
    has_tickers = bool(stored_tickers)
    has_data = _has_return_data(stored_tickers) if has_tickers else True

    # --- Frozen: past the hard cutoff ------------------------------------
    if age_days > _EVENT_AGE_FROZEN_DAYS and has_data:
        natural = "frozen"
        if force:
            # Forced refresh bypasses the frozen rule but still uses the
            # older-event threshold (24h).
            status = "stale"
        else:
            status = "frozen"
        return {
            "status": status,
            "natural_status": natural,
            "event_age_days": age_days,
            "hours_since_check": hours,
            "refresh_threshold_hours": None if not force else _REFRESH_OLDER_HOURS,
            "reason": (
                f"Event is {age_days}d old (> {_EVENT_AGE_FROZEN_DAYS}d frozen cutoff); "
                f"{'forced refresh' if force else 'archived, no refresh'}"
            ),
        }

    # --- Legacy: row pre-dates the freshness column ----------------------
    if last_check is None or hours is None:
        threshold = _refresh_threshold_for(age_days)
        return {
            "status": "legacy",
            "natural_status": "legacy",
            "event_age_days": age_days,
            "hours_since_check": None,
            "refresh_threshold_hours": threshold,
            "reason": (
                "Row has no last_market_check_at yet "
                "(pre-migration); refreshing to stamp."
            ),
        }

    # --- Legacy: row has tickers but no numeric returns ------------------
    # A row that was saved with a skeletal tickers list (no return data)
    # needs to be populated on first read, independent of age.
    if has_tickers and not has_data:
        threshold = _refresh_threshold_for(age_days)
        return {
            "status": "legacy",
            "natural_status": "legacy",
            "event_age_days": age_days,
            "hours_since_check": round(hours, 2),
            "refresh_threshold_hours": threshold,
            "reason": (
                "Row has tickers but no numeric return data; "
                "refreshing to populate."
            ),
        }

    # --- Live: apply the age-aware threshold -----------------------------
    threshold = _refresh_threshold_for(age_days)
    if hours >= threshold:
        return {
            "status": "stale",
            "natural_status": "stale",
            "event_age_days": age_days,
            "hours_since_check": round(hours, 2),
            "refresh_threshold_hours": threshold,
            "reason": (
                f"Last check was {hours:.1f}h ago, "
                f"above the {threshold}h window for a {age_days}d-old event"
            ),
        }

    return {
        "status": "fresh",
        "natural_status": "fresh",
        "event_age_days": age_days,
        "hours_since_check": round(hours, 2),
        "refresh_threshold_hours": threshold,
        "reason": (
            f"Last check was {hours:.1f}h ago, "
            f"within the {threshold}h window for a {age_days}d-old event"
        ),
    }


def should_refresh(staleness: dict) -> bool:
    """True when the caller should re-run the provider check."""
    return staleness.get("status") in ("stale", "legacy")


# ---------------------------------------------------------------------------
# Merge helper: splice fresh return numbers onto stored ticker dicts
# ---------------------------------------------------------------------------


def _merge_followup_into_stored(
    stored: list[dict],
    followup: list[dict],
) -> list[dict]:
    """Return new ticker dicts with fresh return / direction fields.

    ``followup_check`` returns a compact schema (symbol, role, return_1d,
    return_5d, return_20d, direction, anchor_date).  Stored ticker rows
    carry additional fields populated by the original ``market_check``
    call (label, volume_ratio, vs_xle_5d, spark).  We overlay the fresh
    numbers onto the stored rows so downstream consumers see both.

    Tickers in ``stored`` without a matching follow-up entry pass through
    unchanged — that's the right fallback when a symbol was delisted or
    temporarily unfetchable.
    """
    if not stored:
        return []
    by_symbol: dict[str, dict] = {}
    for row in followup or []:
        sym = row.get("symbol")
        if sym:
            by_symbol[sym] = row

    # Dedupe stored ticker rows by symbol on the way out and copy any
    # mutable sub-lists (``spark``) so two emitted tickers can never
    # share the same underlying sequence reference.  Defensive: this
    # is the boundary at which cached-response payloads land on the
    # API contract.
    out: list[dict] = []
    seen: set[str] = set()
    for t in stored:
        sym = t.get("symbol")
        if not sym or sym in seen:
            continue
        seen.add(sym)
        fu = by_symbol.get(sym)
        merged = dict(t)
        spark_src = merged.get("spark")
        if isinstance(spark_src, list):
            merged["spark"] = list(spark_src)
        if fu:
            for k in ("return_1d", "return_5d", "return_20d"):
                v = fu.get(k)
                if v is not None:
                    merged[k] = v
            if fu.get("direction") is not None:
                merged["direction_tag"] = fu["direction"]
            if fu.get("anchor_date"):
                merged.setdefault("anchor_date", fu["anchor_date"])
        out.append(merged)
    return out


# ---------------------------------------------------------------------------
# Public: imperative refresh
# ---------------------------------------------------------------------------


def refresh_market_for_saved_event(
    event: dict,
    *,
    force: bool = False,
    now: Optional[_dt] = None,
    followup_check_fn: Optional[Any] = None,
    market_check_fn: Optional[Any] = None,
    persist_fn: Optional[Any] = None,
) -> dict[str, Any]:
    """Return a market block for a saved event, refreshing it if stale.

    Contract:

      * Input ``event`` is the dict returned by ``db.load_event_by_id`` or
        ``db.find_cached_analysis`` — must include ``id``, ``market_tickers``,
        ``market_note``, ``event_date`` / ``timestamp`` and
        ``last_market_check_at``.
      * Fresh / frozen (unforced) rows return immediately with the stored
        payload unchanged — no provider call, no DB write.
      * Stale / legacy / forced-frozen rows pull fresh returns via
        ``followup_check`` (event-dated) or ``market_check`` (rolling),
        merge them onto the stored rows, and persist through
        ``db.update_event_market_refresh``.  On DB write failure the
        refreshed tickers are still returned to the caller.
      * All exceptions from the provider path are logged and swallowed;
        the stored payload is returned as a graceful fallback.

    The provider functions are injected so the api layer can hand in its
    own (patched-in-tests) references for ``followup_check`` and
    ``market_check``.  ``persist_fn`` defaults to
    ``db.update_event_market_refresh`` and is overridable for tests that
    want to observe the write.

    The returned dict mirrors the shape consumed by the existing
    ``_build_cached_response`` helper:

        {
            "tickers": [...],
            "note": "...",
            "details": {},
            "last_market_check_at": "...",
            "market_check_staleness": "fresh" | "stale_refreshed" | "frozen" | ...
        }
    """
    now_dt = now or _dt.now()
    staleness = compute_staleness(event, now=now_dt, force=force)

    stored_tickers = list(event.get("market_tickers") or [])
    stored_note = event.get("market_note") or ""
    last_check = event.get("last_market_check_at")

    base_payload: dict[str, Any] = {
        "tickers": stored_tickers,
        "note": stored_note,
        "details": {},
        "last_market_check_at": last_check,
        "market_check_staleness": staleness["status"],
        "freshness_reason": staleness["reason"],
        "event_age_days": staleness["event_age_days"],
    }

    if not should_refresh(staleness):
        return base_payload

    # Resolve injectable provider entry points.  Late imports so this
    # module stays cheap to import and so we don't race circular-import
    # order during app boot.
    if followup_check_fn is None or market_check_fn is None:
        try:
            from market_check import (
                followup_check as _default_followup,
                market_check as _default_market_check,
            )
        except Exception:  # pragma: no cover — market_check should always import
            _log.warning(
                "refresh_market_for_saved_event: market_check import failed",
                exc_info=True,
            )
            return base_payload
        if followup_check_fn is None:
            followup_check_fn = _default_followup
        if market_check_fn is None:
            market_check_fn = _default_market_check

    event_date = event.get("event_date")
    try:
        if event_date and stored_tickers:
            followup = followup_check_fn(stored_tickers, event_date)
            new_tickers = _merge_followup_into_stored(stored_tickers, followup)
            new_note = stored_note
        else:
            # Rolling mode — re-run market_check against the stored
            # beneficiary/loser split.  Preserves behaviour for events
            # that were analysed without an explicit event_date.
            bens = [
                t["symbol"] for t in stored_tickers
                if t.get("role") == "beneficiary" and t.get("symbol")
            ]
            losers = [
                t["symbol"] for t in stored_tickers
                if t.get("role") == "loser" and t.get("symbol")
            ]
            if not bens and not losers:
                # Nothing actionable — fall back to the stored payload
                # but stamp the row so we don't keep retrying.
                new_tickers = stored_tickers
                new_note = stored_note
            else:
                mkt = market_check_fn(bens, losers, event_date=None)
                new_tickers = mkt.get("tickers") or stored_tickers
                new_note = mkt.get("note") or stored_note
    except Exception:
        _log.warning(
            "refresh_market_for_saved_event: provider call failed for event %s",
            event.get("id"),
            exc_info=True,
        )
        return base_payload

    new_last_check = now_dt.replace(microsecond=0).isoformat()

    # Persist.  DB failure is non-fatal — the caller still gets fresh data.
    event_id = event.get("id")
    if event_id is not None:
        if persist_fn is None:
            try:
                from db import update_event_market_refresh as persist_fn  # type: ignore
            except Exception:
                persist_fn = None
        if persist_fn is not None:
            try:
                persist_fn(int(event_id), new_tickers, new_note, new_last_check)
            except Exception:
                _log.warning(
                    "refresh_market_for_saved_event: DB persist failed for event %s",
                    event_id,
                    exc_info=True,
                )

    # Label the refreshed row.  A forced refresh on a frozen row reports
    # "forced_refreshed" so dashboards can distinguish "user asked for it"
    # from the normal stale/legacy paths — the natural_status still reflects
    # the unforced view.
    if staleness["natural_status"] == "frozen" and force:
        new_staleness = "forced_refreshed"
    elif staleness["status"] == "stale":
        new_staleness = "stale_refreshed"
    elif staleness["status"] == "legacy":
        new_staleness = "legacy_refreshed"
    else:
        new_staleness = "forced_refreshed"

    return {
        "tickers": new_tickers,
        "note": new_note,
        "details": {},
        "last_market_check_at": new_last_check,
        "market_check_staleness": new_staleness,
        "freshness_reason": staleness["reason"],
        "event_age_days": staleness["event_age_days"],
    }
