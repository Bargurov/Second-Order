"""Derive the ``mover_context`` block for a single event.

An event that is currently active in one or more mover surfaces
(``/movers/today`` / ``/movers/weekly`` / ``/movers/persistent`` /
``/market-movers``) gets a block on ``GET /events/{id}`` explaining:

  * which surfaces it's on (``active_windows``)
  * the mover surface's own one-line ``surfaced_reason``
  * the primary window's ``strongest_move_5d`` + ``moved_tickers``

Pure composer.  Input is a dict mapping window name → list of
UI-ready mover cards (the same shape ``mover_card_normalizer.to_ui_card``
emits).  The route layer populates those lists from already-cached
mover slices so no new market fetches happen here.
"""

from __future__ import annotations

from typing import Any


# The empty-shape factory.  Every response carries this exact shape
# so consumers never have to null-check individual keys; an inactive
# event lands on ``active_windows=[]`` + empty primary fields.
def empty_mover_context() -> dict[str, Any]:
    return {
        "active_windows":    [],
        "surfaced_reason":   "",
        "strongest_move_5d": None,
        "moved_tickers":     [],
    }


# Window priority for picking the "primary" card when an event is
# active in multiple surfaces.  Fresher / shorter-horizon surfaces
# win because their ``surfaced_reason`` is the most time-relevant for
# a reader seeing the event right now.
_WINDOW_PRIORITY: tuple[str, ...] = (
    "today", "market", "weekly", "persistent",
)


def _find_card(cards: Any, event_id: int) -> dict | None:
    """Return the first card whose ``id`` / ``event_id`` matches."""
    if not isinstance(cards, list):
        return None
    for c in cards:
        if not isinstance(c, dict):
            continue
        if c.get("id") == event_id or c.get("event_id") == event_id:
            return c
    return None


# Public closed-set vocabulary for filter validation at the route
# layer — the four mover surfaces the filter contract pins.
MOVER_WINDOW_IDS: tuple[str, ...] = _WINDOW_PRIORITY


def build_event_window_index(
    slices: dict[str, list[dict]] | None,
) -> dict[int, list[str]]:
    """Invert ``slices`` into ``{event_id: [active_windows]}``.

    Walks each slice once, collecting the windows each ``event_id``
    appears on in priority order.  Route-layer filters use this index
    so the cost of four slice reads is amortised across every
    candidate event rather than repeated per-event.
    """
    out: dict[int, list[str]] = {}
    if not isinstance(slices, dict):
        return out
    for window in _WINDOW_PRIORITY:
        cards = slices.get(window)
        if not isinstance(cards, list):
            continue
        for c in cards:
            if not isinstance(c, dict):
                continue
            eid = c.get("id") if c.get("id") is not None else c.get("event_id")
            if not isinstance(eid, int) or isinstance(eid, bool):
                continue
            bucket = out.setdefault(eid, [])
            if window not in bucket:
                bucket.append(window)
    return out


def build_mover_context(
    event_id: Any,
    slices: dict[str, list[dict]] | None,
) -> dict[str, Any]:
    """Compose the ``mover_context`` block for one event.

    ``slices`` keys must be a subset of ``_WINDOW_PRIORITY``.  Values
    are lists of UI-ready mover cards (the projection emitted by
    ``mover_card_normalizer.to_ui_card``) so the composer can read
    ``surfaced_reason`` / ``strongest_move_5d`` / ``moved_tickers``
    without knowing the underlying raw-card fields.

    Returns the full empty shape when ``event_id`` is missing / None
    or when the event isn't active in any slice.
    """
    if not isinstance(event_id, int) or isinstance(event_id, bool):
        return empty_mover_context()
    if not isinstance(slices, dict) or not slices:
        return empty_mover_context()

    active: list[str] = []
    primary: dict | None = None
    for window in _WINDOW_PRIORITY:
        match = _find_card(slices.get(window), event_id)
        if match is None:
            continue
        active.append(window)
        if primary is None:
            primary = match

    if not active or primary is None:
        return empty_mover_context()

    return {
        "active_windows":    active,
        "surfaced_reason":   str(primary.get("surfaced_reason") or ""),
        "strongest_move_5d": primary.get("strongest_move_5d"),
        "moved_tickers":     list(primary.get("moved_tickers") or []),
    }
