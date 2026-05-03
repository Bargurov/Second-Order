"""
overlay_sanitize.py

Consistent scrubbing + degraded-state marking for persisted/frozen overlay
blocks and for mover cards before serialization.

What it adds
------------
Until now each overlay block had its own ad-hoc sanitizer (or none).  When
a frozen-archive read returned an empty dict, the caller silently rendered
nothing — the frontend had no way to distinguish "no data applicable here"
from "data corrupted / lost".  This module introduces a uniform contract:

    Every persisted overlay block emitted by the API carries
    { available, stale, degraded, degraded_reason } — even when the
    underlying data is empty.  Silent ``{}`` fallbacks are replaced with
    an explicit degraded block so the UI can render a degraded pill.

Design
------
- Pure functions.  No I/O.  Idempotent — safe to call on already-sanitized
  blocks.
- ``sanitize_overlay_block`` takes whatever the DB / composer produced and
  returns a dict with the four marker fields guaranteed to be present.
  NaN/inf values are scrubbed to None (piggybacks on the same semantics
  used by ``_sanitize_floats`` in api.py).
- ``sanitize_mover_card`` adds ``data_quality`` / ``data_quality_reason``
  to each mover card based on ``last_market_check_at`` age.
- Neither function invents data.  They surface what IS known about
  freshness / quality so downstream consumers can trust the contract.

Public API
----------
    sanitize_overlay_block(block, *, name="", magnitude_caps=None) -> dict
    sanitize_mover_card(card, *, now=None, stale_after_days=7) -> dict
    sanitize_floats(obj) -> obj                # re-export for callers
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


__all__ = [
    "sanitize_overlay_block",
    "sanitize_mover_card",
    "sanitize_floats",
    "MOVER_STALE_AFTER_DAYS",
]


# ---------------------------------------------------------------------------
# NaN / inf scrub  (mirrors api._sanitize_floats; extracted for reuse)
# ---------------------------------------------------------------------------

def sanitize_floats(obj: Any) -> Any:
    """Recursively replace NaN / ±inf with None.

    Kept standalone so routes that don't import api.py can scrub floats
    locally without pulling the whole API module.
    """
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_floats(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Overlay-block sanitizer
# ---------------------------------------------------------------------------

def _apply_magnitude_caps(block: dict, caps: dict) -> tuple[dict, bool]:
    """Clamp any top-level numeric field whose absolute value exceeds its cap.

    Returns (scrubbed_block, tripped_flag).  Fields that trip the cap are
    cleared to None rather than coerced to the cap value — a corrupt
    value is always less safe than a missing one.
    """
    tripped = False
    for key, cap in caps.items():
        val = block.get(key)
        if isinstance(val, (int, float)) and not (
            isinstance(val, bool)  # bool is subclass of int
        ):
            try:
                if abs(float(val)) > float(cap):
                    block[key] = None
                    tripped = True
            except (TypeError, ValueError):
                continue
    return block, tripped


def sanitize_overlay_block(
    block: Any,
    *,
    name: str = "",
    magnitude_caps: Optional[dict[str, float]] = None,
) -> dict:
    """Normalize a persisted overlay block to the uniform degraded contract.

    Always returns a dict containing at minimum:
      ``{"available", "stale", "degraded", "degraded_reason"}``

    Semantics
    ---------
    - ``block`` is ``None`` / ``{}`` / non-dict  →  returns the explicit
      degraded block ``{"available": False, "stale": True,
      "degraded": True, "degraded_reason": "no persisted {name} data"}``.
    - ``block`` has content but lacks ``available``  →  default to
      ``available=True`` (the composer was confident enough to emit it),
      ``stale=False``, ``degraded=False``.
    - ``block.available`` is falsy but no ``stale`` set  →  mark stale
      and degraded, preserving the composer's content.
    - ``magnitude_caps`` tripping  →  flips ``degraded=True`` and appends
      a cap-trip reason.
    - NaN / inf values are scrubbed throughout.

    ``name`` is embedded in the default degraded_reason so downstream
    telemetry / UI tooltips can cite the overlay type ("no persisted
    shock_decomposition data").
    """
    # Normalize non-dict / empty inputs to the explicit degraded block.
    if not isinstance(block, dict) or not block:
        label = name or "overlay"
        return {
            "available":        False,
            "stale":            True,
            "degraded":         True,
            "degraded_reason":  f"no persisted {label} data",
        }

    # Work on a shallow copy so frozen-archive callers never mutate
    # the cached dict (tests hit this with shared fixtures).
    import copy
    block = copy.deepcopy(block)

    # Float scrub first — NaN/inf shouldn't pollute downstream checks.
    block = sanitize_floats(block)

    tripped = False
    if magnitude_caps:
        block, tripped = _apply_magnitude_caps(block, magnitude_caps)

    # Normalize marker fields.  Treat missing fields as "composer was
    # confident and emitted a live block"; this preserves legacy rows
    # that pre-date the marker contract.
    available_raw = block.get("available")
    if available_raw is None:
        # No explicit marker → assume available.  Exception: if the block
        # has only the degraded-shape reason fields, call it unavailable.
        available = True
    else:
        available = bool(available_raw)

    stale = bool(block.get("stale")) if "stale" in block else False

    degraded_reasons: list[str] = []
    if tripped:
        degraded_reasons.append(
            f"magnitude caps tripped in {name or 'overlay'}"
        )
    if not available:
        stale = True
        if not degraded_reasons:
            degraded_reasons.append(
                f"{name or 'overlay'} marked unavailable by composer"
            )

    existing_reason = block.get("degraded_reason")
    if isinstance(existing_reason, str) and existing_reason.strip():
        degraded_reasons.insert(0, existing_reason.strip())

    degraded = bool(degraded_reasons)
    reason = "; ".join(dict.fromkeys(r for r in degraded_reasons if r))

    block["available"] = available
    block["stale"] = stale
    block["degraded"] = degraded
    block["degraded_reason"] = reason
    return block


# ---------------------------------------------------------------------------
# Mover sanitizer
# ---------------------------------------------------------------------------

# Market movers stored with a ``last_market_check_at`` older than this
# are flagged as stale in the serialized output.
MOVER_STALE_AFTER_DAYS: int = 7


def _parse_ts(ts: Any) -> Optional[datetime]:
    """Parse a persisted ISO timestamp; return None on any failure.

    Accepts both naive and timezone-aware strings.  Tolerates trailing 'Z'.
    """
    if not isinstance(ts, str) or not ts.strip():
        return None
    text = ts.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def sanitize_mover_card(
    card: Any,
    *,
    now: Optional[datetime] = None,
    stale_after_days: int = MOVER_STALE_AFTER_DAYS,
) -> dict:
    """Scrub a single mover card and attach data-quality markers.

    Adds the following fields (overwrites any existing values — this is
    the sanitized contract):

      data_quality         : "ok" | "stale" | "degraded"
      data_quality_reason  : str  (empty when "ok")
      data_quality_age_days: int | None  (days since last_market_check_at)

    Additionally runs ``sanitize_floats`` over the card so NaN/inf in
    return_5d / spark / impact can never leak into the JSON payload.
    """
    if not isinstance(card, dict):
        return card  # type: ignore[return-value]

    card = sanitize_floats(dict(card))

    ts_raw = card.get("last_market_check_at")
    ts = _parse_ts(ts_raw)
    age_days: Optional[int] = None
    quality = "ok"
    reason = ""

    if ts is None:
        quality = "degraded"
        reason = "missing last_market_check_at"
    else:
        now_dt = now or datetime.now(tz=ts.tzinfo)
        # If the stored timestamp is naive but we were given a tz-aware
        # ``now``, make them comparable by assuming UTC on the naive side.
        if ts.tzinfo is None and now_dt.tzinfo is not None:
            ts = ts.replace(tzinfo=timezone.utc)
        if now_dt.tzinfo is None and ts.tzinfo is not None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
        try:
            delta = now_dt - ts
        except TypeError:
            delta = timedelta(days=0)
        age_days = max(0, int(delta.total_seconds() // 86400))
        if age_days > stale_after_days:
            quality = "stale"
            reason = f"market check {age_days}d old"

    card["data_quality"] = quality
    card["data_quality_reason"] = reason
    card["data_quality_age_days"] = age_days
    return card
