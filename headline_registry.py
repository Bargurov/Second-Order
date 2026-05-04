"""Headline registry — lifecycle tracking for every ingested headline.

See docs/superpowers/specs/2026-05-03-headline-registry-design.md for
the full design.  This module exposes the non-DB surface:

  * is_expired_low_impact   — pure decision helper (no DB)
  * stamp_expired_if_observed — idempotent lazy-stamp (writes to DB)
  * filter_expired_low_impact — bulk page filter for read sites
  * advance_state            — thin wrapper around db.update_registry_state
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

_log = logging.getLogger("second_order.headline_registry")

_TTL_ENV_VAR = "HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS"
_DEFAULT_TTL_DAYS = 5


def _ttl_days() -> int:
    raw = os.environ.get(_TTL_ENV_VAR)
    if not raw:
        return _DEFAULT_TTL_DAYS
    try:
        value = int(raw)
        return value if value > 0 else _DEFAULT_TTL_DAYS
    except (TypeError, ValueError):
        return _DEFAULT_TTL_DAYS


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace("Z", ""))
        except ValueError:
            return None


def _title_key(headline: str) -> str:
    """Reuse the canonical normalizer the cluster store + ingestion use."""
    from news_sources import _dedup_key
    return _dedup_key(headline or "")


def is_expired_low_impact(
    event_row: dict,
    registry_analyzed_at: Optional[str] = None,
    registry_impact_level: Optional[str] = None,
    now: Optional[datetime] = None,
) -> bool:
    """True when an event is low-impact AND its analyzed_at is past TTL.

    Impact comes from ``event_row['conviction']['impact_level']`` when
    present; otherwise falls back to ``registry_impact_level``.  The
    fallback is the live path for ``/events`` listing rows — DB rows
    don't carry a ``conviction`` block, so the registry is the source
    of truth there.  Helper-level callers that hand-build rows with a
    conviction block keep working unchanged.

    Uses ``registry_analyzed_at`` when provided; falls back to
    ``event_row['timestamp']`` only when the registry analyzed_at is
    missing (covers events analyzed before the registry existed).
    """
    impact = (event_row.get("conviction") or {}).get("impact_level")
    if not impact:
        impact = registry_impact_level
    if impact != "low":
        return False
    anchor = registry_analyzed_at or event_row.get("timestamp")
    if not anchor:
        return False
    parsed = _parse_iso(anchor)
    if parsed is None:
        return False
    cutoff = (now or datetime.now()) - timedelta(days=_ttl_days())
    return parsed < cutoff


def stamp_expired_if_observed(
    event_row: dict,
    registry_analyzed_at: Optional[str] = None,
    now: Optional[datetime] = None,
) -> None:
    """Idempotent UPSERT setting state='expired_low_impact' + expired_at.

    Idempotency: forward-only ``update_registry_state`` won't regress
    the state, and we skip the write entirely when the registry already
    shows the row in ``expired_low_impact`` so ``expired_at`` does not
    drift forward on re-observation (the diagnostics endpoint reads
    ``expired_at`` to compute ``expired_count_24h``).
    """
    if not is_expired_low_impact(event_row, registry_analyzed_at, now):
        return
    headline = event_row.get("headline") or ""
    title_key = _title_key(headline)
    if not title_key:
        return
    try:
        from db import DB_FILE, _db_ready, update_registry_state
        if not _db_ready:
            return
        import sqlite3
        with sqlite3.connect(DB_FILE) as conn:
            row = conn.execute(
                "SELECT 1 FROM headline_registry "
                "WHERE title_key = ? AND state = 'expired_low_impact' "
                "LIMIT 1",
                (title_key,),
            ).fetchone()
        if row:
            return  # already stamped
        now_iso = (now or datetime.now()).replace(microsecond=0).isoformat()
        update_registry_state(
            title_key=title_key,
            new_state="expired_low_impact",
            expired_at=now_iso,
        )
    except Exception:
        _log.warning(
            "headline_registry.stamp_expired_if_observed failed",
            exc_info=True,
        )


def filter_expired_low_impact(
    event_rows: list[dict],
    now: Optional[datetime] = None,
) -> list[dict]:
    """Drop expired-low-impact rows; lazy-stamp them in the registry.

    One DB round-trip per page (bulk SELECT of analyzed_at for the
    page's title_keys).  Returns surviving rows in original order.
    """
    if not event_rows:
        return []
    title_keys: list[str] = []
    per_row_keys: list[str] = []
    for row in event_rows:
        tk = _title_key(row.get("headline") or "")
        per_row_keys.append(tk)
        if tk:
            title_keys.append(tk)
    if not title_keys:
        survivors: list[dict] = []
        for row in event_rows:
            if is_expired_low_impact(row, registry_analyzed_at=None, now=now):
                stamp_expired_if_observed(row, registry_analyzed_at=None, now=now)
                continue
            survivors.append(row)
        return survivors
    try:
        from db import load_registry_anchors_for_keys
        anchor_map = load_registry_anchors_for_keys(list(set(title_keys)))
    except Exception:
        _log.warning(
            "headline_registry.filter_expired_low_impact: bulk load failed",
            exc_info=True,
        )
        anchor_map = {}
    survivors = []
    for row, tk in zip(event_rows, per_row_keys):
        anchor = anchor_map.get(tk) or {}
        analyzed_at = anchor.get("analyzed_at")
        impact_level = anchor.get("impact_level")
        if is_expired_low_impact(
            row,
            registry_analyzed_at=analyzed_at,
            registry_impact_level=impact_level,
            now=now,
        ):
            stamp_expired_if_observed(
                row, registry_analyzed_at=analyzed_at, now=now,
            )
            continue
        survivors.append(row)
    return survivors


def advance_state(
    *,
    title_key: str,
    new_state: Optional[str] = None,
    event_id: Optional[int] = None,
    impact_level: Optional[str] = None,
    analyzed_at: Optional[str] = None,
    last_skip_reason: Optional[str] = None,
) -> None:
    """Thin pass-through to ``db.update_registry_state``.

    Centralised here so callers don't import db.update_registry_state
    directly — keeps the state machine surface in one module.
    """
    if not title_key:
        return
    try:
        from db import update_registry_state
        update_registry_state(
            title_key=title_key,
            new_state=new_state,
            event_id=event_id,
            impact_level=impact_level,
            analyzed_at=analyzed_at,
            last_skip_reason=last_skip_reason,
        )
    except Exception:
        _log.warning(
            "headline_registry.advance_state failed for %s", title_key,
            exc_info=True,
        )
