"""Demo Weekly Market source.

Read-only demo source that exercises the existing Weekly mover stream
and applies the production canonicalization helper
(:func:`routes.weekly_canonicalization.collapse_weekly_duplicates`)
so duplicate-shaped stories collapse into a single canonical card
carrying ``duplicate_count`` and ``grouped_event_ids``.

The module is not registered in ``api.py``.  It is a pure-Python
source other callers (an operator script, a future demo route) can
import.  Production ``/movers/weekly`` is not modified.

Read-only by construction
-------------------------

* No DB reads or writes at module load.  The default loader lazily
  imports ``movers_cache`` and calls ``get_slice('weekly', ...)``
  exactly once per ``build_demo_weekly_market`` call.
* No ``yfinance``, ``market_data``, ``price_cache.fetch_*``, LLM,
  or paid provider call.  No network access.
* No FastAPI surface is imported at module load.
* No mutation of the events DB, ``news_inbox.json``, the news
  cache, or the movers cache by this module.  The canonicalization
  helper itself is read-only (see its docstring).
* Defensive on bad input: a non-list / non-dict entry never raises;
  it is dropped or passed through as appropriate and surfaces in
  ``warnings``.

Output contract::

    {
      "ok":                          bool,
      "section":                     "weekly",
      "items":                       [item, ...],
      "count":                       int,
      "duplicate_groups_collapsed":  int,
      "warnings":                    [str, ...],
      "errors":                      [str, ...],
    }

Each item carries (optional fields omitted when the source card
does not provide them)::

    {
      "event_id":          int | None,
      "headline":          str,
      "event_date":        str,
      "tickers":           [str, ...],          # optional
      "primary_ticker":    str,                 # optional
      "mechanism_family":  str,                 # optional
      "duplicate_count":   int,
      "grouped_event_ids": [int, ...],
      "caution_label":     str,
    }

Conservative wording — the source surfaces every card with a
``caution_label`` marking it as a demo row that requires operator
review before it can be relied on.  The source never claims a card
is proven, validated, fit to trade, or production-ready.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from routes.weekly_canonicalization import collapse_weekly_duplicates


SECTION_NAME: str = "weekly"

# Uniform label attached to every demo item so downstream consumers
# can never confuse a demo card with a production-graded one.
CAUTION_LABEL: str = (
    "demo Weekly Market source; operator review required before use"
)

# Default page size for the lazy loader.  Mirrors the production
# ``/movers/weekly`` default so the demo source surfaces the same
# slice depth without re-deriving it.
_DEFAULT_LIMIT: int = 10


def load_weekly_market_items(*, limit: int = _DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """Default loader for Weekly cards.  Patchable seam.

    Lazily imports ``movers_cache`` so the demo module's top-level
    import surface does not pull DB-adjacent code in at parse time.
    Tests typically pass synthetic items to
    :func:`build_demo_weekly_market` directly and never invoke this
    loader.
    """
    import movers_cache  # noqa: PLC0415 — intentional lazy import

    return movers_cache.get_slice("weekly", limit=limit)


def build_demo_weekly_market(
    items: Iterable[Any] | None = None,
    *,
    limit: int = _DEFAULT_LIMIT,
    loader: Callable[..., list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build the demo Weekly Market envelope.

    Parameters
    ----------
    items : iterable of dicts, optional
        Pre-loaded Weekly mover cards.  When omitted, the source
        calls ``loader`` (or :func:`load_weekly_market_items` by
        default) to read items from the existing Weekly cache.
    limit : int
        Page size passed to the default loader when ``items`` is
        ``None``.  Ignored when ``items`` is supplied.
    loader : callable, optional
        Override for the default loader.  Useful in tests that want
        to exercise the load → canonicalize → project path without
        patching the module-level seam.
    """
    warnings: list[str] = []
    errors:   list[str] = []

    if items is None:
        load_fn = loader if loader is not None else load_weekly_market_items
        try:
            items = load_fn(limit=limit)
        except Exception as e:  # noqa: BLE001 — surface, do not crash
            errors.append(
                f"weekly_market_load_failed: {type(e).__name__}: {e}"
            )
            items = []

    if not isinstance(items, list):
        warnings.append("loader returned non-list weekly items; treating as empty")
        items = []

    raw_cards: list[dict[str, Any]] = []
    dropped_non_dict = 0
    for entry in items:
        if isinstance(entry, dict):
            raw_cards.append(entry)
        else:
            dropped_non_dict += 1
    if dropped_non_dict:
        warnings.append(
            f"dropped {dropped_non_dict} non-dict weekly card(s) before canonicalization"
        )

    collapsed = collapse_weekly_duplicates(raw_cards)

    duplicate_groups_collapsed = 0
    projected: list[dict[str, Any]] = []
    for card in collapsed:
        if not isinstance(card, dict):
            # ``collapse_weekly_duplicates`` is defensive — but be
            # explicit about the contract here.
            continue
        dc = card.get("duplicate_count")
        if isinstance(dc, int) and not isinstance(dc, bool) and dc > 0:
            duplicate_groups_collapsed += 1
        projected.append(_project_item(card))

    return {
        "ok":                         not errors,
        "section":                    SECTION_NAME,
        "items":                      projected,
        "count":                      len(projected),
        "duplicate_groups_collapsed": duplicate_groups_collapsed,
        "warnings":                   warnings,
        "errors":                     errors,
    }


def _project_item(card: dict[str, Any]) -> dict[str, Any]:
    """Project a (possibly canonicalized) Weekly card to the demo
    item shape.

    Required fields are always present.  Optional fields
    (``tickers``, ``primary_ticker``, ``mechanism_family``) are
    included only when the source card carries a non-empty value of
    the expected type; the demo source never invents them.
    """
    out: dict[str, Any] = {}

    eid_raw = card.get("event_id")
    event_id: int | None
    if isinstance(eid_raw, int) and not isinstance(eid_raw, bool):
        event_id = eid_raw
    else:
        event_id = None
    out["event_id"] = event_id

    headline = card.get("headline")
    out["headline"] = headline if isinstance(headline, str) else ""

    event_date = card.get("event_date")
    out["event_date"] = event_date if isinstance(event_date, str) else ""

    tickers = card.get("tickers")
    if isinstance(tickers, list):
        clean = [t for t in tickers if isinstance(t, str) and t]
        if clean:
            out["tickers"] = clean

    primary_ticker = card.get("primary_ticker")
    if isinstance(primary_ticker, str) and primary_ticker:
        out["primary_ticker"] = primary_ticker

    mechanism_family = card.get("mechanism_family")
    if isinstance(mechanism_family, str) and mechanism_family:
        out["mechanism_family"] = mechanism_family

    dc_raw = card.get("duplicate_count")
    if isinstance(dc_raw, int) and not isinstance(dc_raw, bool) and dc_raw > 0:
        out["duplicate_count"] = dc_raw
    else:
        out["duplicate_count"] = 0

    gei_raw = card.get("grouped_event_ids")
    if (
        isinstance(gei_raw, list)
        and all(isinstance(x, int) and not isinstance(x, bool) for x in gei_raw)
        and gei_raw
    ):
        out["grouped_event_ids"] = list(gei_raw)
    elif event_id is not None:
        # Singleton (canonicalization left the card untouched) — every
        # demo item still surfaces a ``grouped_event_ids`` list so
        # downstream consumers can iterate uniformly.  The list
        # contains the card's own ``event_id`` and nothing else.
        out["grouped_event_ids"] = [event_id]
    else:
        out["grouped_event_ids"] = []

    out["caution_label"] = CAUTION_LABEL

    return out


__all__ = (
    "SECTION_NAME",
    "CAUTION_LABEL",
    "build_demo_weekly_market",
    "load_weekly_market_items",
)
