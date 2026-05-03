"""Versioned coverage registry — one explicit source of truth for the
feeds we ingest and the markets we monitor.

Why this file
-------------
Feed coverage used to live half in ``news_fetch.DEFAULT_FEEDS``
(the raw URL list) and half in ``feed_registry.FEED_METADATA`` (sector
and region tags).  Market-watchlist coverage lived in
``market_universe.LIQUID_MARKETS`` + ``LIQUID_MARKET_INFO``.  There
was no single place to answer a review-style question like "which
research lane owns Asia macro feeds?" or "what's the tier of the
emerging-markets coverage bucket?"

This module unifies those two dimensions into one declarative
registry stamped with a ``version`` and per-group ownership /
category / tier metadata.  The existing modules keep their raw data —
this registry does not replace them.  Instead, drift tests
(``tests/test_coverage_registry.py``) cross-check that every
``FEED_METADATA`` entry and every ``LIQUID_MARKETS`` entry belongs to
exactly one registry group and vice versa, so silent coverage
changes fail CI.

Design discipline
-----------------
* Pure module — no I/O beyond deep-copying the dict.
* ``load_coverage_registry()`` returns a deep copy so callers can
  mutate without polluting the module-level constant.
* ``validate_coverage_registry(reg)`` is the single validator.  It
  raises ``ValueError`` with a descriptive message on any shape
  violation; there is no "soft warning" path.
* All enums (categories, tiers, asset classes) are pinned as module
  constants so tests can assert they haven't drifted.
"""

from __future__ import annotations

import copy
from typing import Any, Iterator


# ---------------------------------------------------------------------------
# Pinned version + enums.
# ---------------------------------------------------------------------------

COVERAGE_REGISTRY_VERSION: str = "2026.04.01"

FEED_CATEGORIES: frozenset[str] = frozenset({
    "macro_wire",       # wire services / headline macro
    "financial_media",  # business/finance press, ticker-driven desks
    "policy",           # central banks + multilaterals
    "commodity",        # energy, metals, shipping
    "trade",            # export controls, sanctions, tariffs
    "regional_macro",   # regional macro desks (EU/Asia/EM)
    "geopolitical",     # geopolitics, defence
})

COVERAGE_TIERS: tuple[str, ...] = ("high", "medium", "low")

# Mirrors the ``asset_class`` values carried by market_universe.LIQUID_MARKET_INFO
# — the market-group asset_class field must stay a subset of this set.
ASSET_CLASSES: frozenset[str] = frozenset({
    "equity_index", "commodity", "currency", "rate",
})


_REQUIRED_FEED_GROUP_KEYS: frozenset[str] = frozenset({
    "id", "owner", "category", "tier",
    "description", "added_at", "members",
})

_REQUIRED_MARKET_GROUP_KEYS: frozenset[str] = frozenset({
    "id", "owner", "asset_class",
    "description", "added_at", "members",
})


# ---------------------------------------------------------------------------
# The registry itself.  Each group's ``members`` is the authoritative
# membership list for that bucket.  Adding or removing a feed /
# market only requires editing the registry — drift tests will yell
# if the corresponding module (FEED_METADATA / LIQUID_MARKETS)
# doesn't match.
# ---------------------------------------------------------------------------

COVERAGE_REGISTRY: dict[str, Any] = {
    "version":    COVERAGE_REGISTRY_VERSION,
    "updated_at": "2026-04-19",
    "feed_groups": [
        {
            "id":          "wire_services",
            "owner":       "research",
            "category":    "macro_wire",
            "tier":        "high",
            "description": "Primary global wire services + Tier-1 financial "
                           "newspapers.  Highest trust; first read on every "
                           "macro event.",
            "added_at":    "2025-10-01",
            "members": [
                "Reuters World",
                "AP News",
                "AFP World",
                "WSJ World News",
                "FT World",
                "Bloomberg Markets",
            ],
        },
        {
            "id":          "financial_media",
            "owner":       "research",
            "category":    "financial_media",
            "tier":        "medium",
            "description": "Ticker-driven US financial press.  Lower trust "
                           "per-article but critical for same-day equity read.",
            "added_at":    "2025-10-01",
            "members": [
                "MarketWatch",
                "CNBC World",
                "Yahoo Finance",
                "Investing.com",
            ],
        },
        {
            "id":          "central_banks_policy",
            "owner":       "macro",
            "category":    "policy",
            "tier":        "high",
            "description": "Central bank + multilateral press releases.  "
                           "Primary-source policy signal.",
            "added_at":    "2025-10-01",
            "members": [
                "Fed Press Releases",
                "ECB Press Releases",
                "IMF News",
                "World Bank",
            ],
        },
        {
            "id":          "energy_commodities",
            "owner":       "commodities_desk",
            "category":    "commodity",
            "tier":        "medium",
            "description": "Energy / commodity / shipping desks.  Used for "
                           "mechanism-family tagging on supply / commodity "
                           "shock events.",
            "added_at":    "2025-10-01",
            "members": [
                "EIA Energy",
                "OilPrice.com",
                "Rigzone",
                "S&P Global Commodities",
                "Mining.com",
                "Freight & Shipping",
            ],
        },
        {
            "id":          "trade_controls",
            "owner":       "policy",
            "category":    "trade",
            "tier":        "high",
            "description": "Sanctions / export control / trade policy "
                           "authorities.  Primary source for tariff + "
                           "sanction events.",
            "added_at":    "2025-10-01",
            "members": [
                "OFAC Sanctions",
                "USTR Trade Policy",
                "Semiconductor Trade",
            ],
        },
        {
            "id":          "asia_pacific",
            "owner":       "geo",
            "category":    "regional_macro",
            "tier":        "medium",
            "description": "Asia-Pacific regional macro desks.  Complements "
                           "wire coverage on EM-Asia and China.",
            "added_at":    "2025-10-01",
            "members": [
                "Nikkei Asia",
                "SCMP Economy",
                "Economic Times",
            ],
        },
        {
            "id":          "europe_macro",
            "owner":       "geo",
            "category":    "regional_macro",
            "tier":        "medium",
            "description": "European macro + world desks.  Secondary read "
                           "on EU monetary / fiscal developments.",
            "added_at":    "2025-10-01",
            "members": [
                "The Guardian Business",
                "BBC Business",
                "BBC World",
                "The Guardian World",
            ],
        },
        {
            "id":          "emerging_markets",
            "owner":       "geo",
            "category":    "regional_macro",
            "tier":        "low",
            "description": "Latin America + Africa regional desks.  Thin "
                           "coverage; use only as corroborating read.",
            "added_at":    "2026-01-15",
            "members": [
                "LatAm Economy",
                "Africa Economy",
            ],
        },
        {
            "id":          "geopolitical_defense",
            "owner":       "geo",
            "category":    "geopolitical",
            "tier":        "medium",
            "description": "Geopolitics + defense desks.  Used for "
                           "ceasefire / de-escalation and defence-sector "
                           "events.",
            "added_at":    "2025-10-01",
            "members": [
                "Al Jazeera Economy",
                "NPR World",
                "Defense News",
            ],
        },
    ],
    "market_groups": [
        {
            "id":          "equity_index_futures",
            "owner":       "markets",
            "asset_class": "equity_index",
            "description": "Primary liquid US equity-index futures (or ETF "
                           "proxies under Polygon).  The core equity read.",
            "added_at":    "2025-10-01",
            "members":     ["ES", "NQ", "RTY"],
        },
        {
            "id":          "commodity_futures",
            "owner":       "markets",
            "asset_class": "commodity",
            "description": "Liquid commodity futures — WTI + gold.  Used "
                           "for supply-shock and safe-haven reads.",
            "added_at":    "2025-10-01",
            "members":     ["CL", "GC"],
        },
        {
            "id":          "fx_majors",
            "owner":       "markets",
            "asset_class": "currency",
            "description": "USD index — the single currency aggregate "
                           "in the default liquid set.  FX cross-rate "
                           "aliases (EURUSD/USDJPY/USDCNY) remain "
                           "resolvable via market_universe for callers "
                           "that need them but are outside the default "
                           "8-market sweep.",
            "added_at":    "2025-10-01",
            "members":     ["DXY"],
        },
        {
            "id":          "rates",
            "owner":       "markets",
            "asset_class": "rate",
            "description": "Benchmark Treasury yields.  Short + long end "
                           "of the curve for rates-regime reads.",
            "added_at":    "2025-10-01",
            "members":     ["2Y", "10Y"],
        },
    ],
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _ensure_nonempty_str(value: Any, *, path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"coverage_registry: {path} must be a non-empty string "
            f"(got {type(value).__name__}: {value!r})"
        )


def _ensure_iso_date(value: Any, *, path: str) -> None:
    _ensure_nonempty_str(value, path=path)
    # We don't need a calendar library — just pin the YYYY-MM-DD shape.
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise ValueError(
            f"coverage_registry: {path} must be ISO YYYY-MM-DD "
            f"(got {value!r})"
        )


def _validate_group_members(
    members: Any, *, path: str, seen: set[str],
) -> list[str]:
    if not isinstance(members, list) or not members:
        raise ValueError(
            f"coverage_registry: {path}.members must be a non-empty list "
            f"(got {type(members).__name__})"
        )
    out: list[str] = []
    local_seen: set[str] = set()
    for i, m in enumerate(members):
        _ensure_nonempty_str(m, path=f"{path}.members[{i}]")
        if m in local_seen:
            raise ValueError(
                f"coverage_registry: {path} has duplicate member {m!r}"
            )
        if m in seen:
            raise ValueError(
                f"coverage_registry: member {m!r} appears in more than one "
                f"group (second occurrence in {path})"
            )
        local_seen.add(m)
        seen.add(m)
        out.append(m)
    return out


def _validate_feed_group(group: Any, *, path: str, seen: set[str]) -> None:
    if not isinstance(group, dict):
        raise ValueError(
            f"coverage_registry: {path} must be a dict "
            f"(got {type(group).__name__})"
        )
    missing = _REQUIRED_FEED_GROUP_KEYS - set(group)
    extra = set(group) - _REQUIRED_FEED_GROUP_KEYS
    if missing:
        raise ValueError(
            f"coverage_registry: {path} missing required keys "
            f"{sorted(missing)}"
        )
    if extra:
        raise ValueError(
            f"coverage_registry: {path} has unknown keys {sorted(extra)}"
        )
    _ensure_nonempty_str(group["id"],          path=f"{path}.id")
    _ensure_nonempty_str(group["owner"],       path=f"{path}.owner")
    _ensure_nonempty_str(group["description"], path=f"{path}.description")
    _ensure_iso_date(group["added_at"],        path=f"{path}.added_at")
    if group["category"] not in FEED_CATEGORIES:
        raise ValueError(
            f"coverage_registry: {path}.category={group['category']!r} "
            f"is not one of {sorted(FEED_CATEGORIES)}"
        )
    if group["tier"] not in COVERAGE_TIERS:
        raise ValueError(
            f"coverage_registry: {path}.tier={group['tier']!r} "
            f"is not one of {list(COVERAGE_TIERS)}"
        )
    _validate_group_members(
        group["members"], path=path, seen=seen,
    )


def _validate_market_group(group: Any, *, path: str, seen: set[str]) -> None:
    if not isinstance(group, dict):
        raise ValueError(
            f"coverage_registry: {path} must be a dict "
            f"(got {type(group).__name__})"
        )
    missing = _REQUIRED_MARKET_GROUP_KEYS - set(group)
    extra = set(group) - _REQUIRED_MARKET_GROUP_KEYS
    if missing:
        raise ValueError(
            f"coverage_registry: {path} missing required keys "
            f"{sorted(missing)}"
        )
    if extra:
        raise ValueError(
            f"coverage_registry: {path} has unknown keys {sorted(extra)}"
        )
    _ensure_nonempty_str(group["id"],          path=f"{path}.id")
    _ensure_nonempty_str(group["owner"],       path=f"{path}.owner")
    _ensure_nonempty_str(group["description"], path=f"{path}.description")
    _ensure_iso_date(group["added_at"],        path=f"{path}.added_at")
    if group["asset_class"] not in ASSET_CLASSES:
        raise ValueError(
            f"coverage_registry: {path}.asset_class="
            f"{group['asset_class']!r} is not one of {sorted(ASSET_CLASSES)}"
        )
    _validate_group_members(
        group["members"], path=path, seen=seen,
    )


def validate_coverage_registry(reg: Any) -> None:
    """Validate a coverage-registry dict in place.

    Raises ``ValueError`` on any shape violation.  Returns ``None`` on
    success.  Idempotent — callers can invoke this after loading or
    after hand-editing the dict without mutating anything.
    """
    if not isinstance(reg, dict):
        raise ValueError(
            "coverage_registry: registry must be a dict "
            f"(got {type(reg).__name__})"
        )
    required_top = {"version", "updated_at", "feed_groups", "market_groups"}
    missing = required_top - set(reg)
    if missing:
        raise ValueError(
            f"coverage_registry: missing top-level keys {sorted(missing)}"
        )
    extra = set(reg) - required_top
    if extra:
        raise ValueError(
            f"coverage_registry: unknown top-level keys {sorted(extra)}"
        )

    _ensure_nonempty_str(reg["version"], path="version")
    _ensure_iso_date(reg["updated_at"],  path="updated_at")

    if not isinstance(reg["feed_groups"], list) or not reg["feed_groups"]:
        raise ValueError(
            "coverage_registry: feed_groups must be a non-empty list"
        )
    if not isinstance(reg["market_groups"], list) or not reg["market_groups"]:
        raise ValueError(
            "coverage_registry: market_groups must be a non-empty list"
        )

    # Per-dimension group ids must be unique.  Feed and market ids live
    # in separate namespaces — a ``fx_majors`` market group doesn't
    # collide with a hypothetical ``fx_majors`` feed group.
    feed_ids: set[str] = set()
    market_ids: set[str] = set()
    feed_members: set[str] = set()
    market_members: set[str] = set()

    for i, group in enumerate(reg["feed_groups"]):
        path = f"feed_groups[{i}]"
        _validate_feed_group(group, path=path, seen=feed_members)
        gid = group["id"]
        if gid in feed_ids:
            raise ValueError(
                f"coverage_registry: duplicate feed_group id {gid!r}"
            )
        feed_ids.add(gid)

    for i, group in enumerate(reg["market_groups"]):
        path = f"market_groups[{i}]"
        _validate_market_group(group, path=path, seen=market_members)
        gid = group["id"]
        if gid in market_ids:
            raise ValueError(
                f"coverage_registry: duplicate market_group id {gid!r}"
            )
        market_ids.add(gid)


# ---------------------------------------------------------------------------
# Deterministic load + typed accessors
# ---------------------------------------------------------------------------

def load_coverage_registry() -> dict[str, Any]:
    """Return a validated deep copy of ``COVERAGE_REGISTRY``.

    The copy isolates callers from module-level mutation.  Validation
    runs on every call so callers never hold a malformed snapshot.
    """
    reg = copy.deepcopy(COVERAGE_REGISTRY)
    validate_coverage_registry(reg)
    return reg


def iter_feed_coverage() -> Iterator[dict[str, Any]]:
    """Yield per-feed coverage rows: ``{feed, group_id, owner, tier, category}``.

    Useful for drift tests + audit tooling that want a flat view.
    """
    for group in COVERAGE_REGISTRY["feed_groups"]:
        for feed in group["members"]:
            yield {
                "feed":     feed,
                "group_id": group["id"],
                "owner":    group["owner"],
                "tier":     group["tier"],
                "category": group["category"],
            }


def iter_market_coverage() -> Iterator[dict[str, Any]]:
    """Yield per-market coverage rows: ``{market, group_id, owner, asset_class}``."""
    for group in COVERAGE_REGISTRY["market_groups"]:
        for market in group["members"]:
            yield {
                "market":      market,
                "group_id":    group["id"],
                "owner":       group["owner"],
                "asset_class": group["asset_class"],
            }


def resolve_feed_group(feed: str) -> str | None:
    """Return the ``group_id`` that owns ``feed``, or ``None`` if unknown."""
    for row in iter_feed_coverage():
        if row["feed"] == feed:
            return row["group_id"]
    return None


def resolve_market_group(market: str) -> str | None:
    """Return the ``group_id`` that owns ``market``, or ``None`` if unknown."""
    m = (market or "").upper()
    for row in iter_market_coverage():
        if row["market"].upper() == m:
            return row["group_id"]
    return None


# Validate on import so any deploy ships a registry that at least
# parses.  Drift tests (which require FEED_METADATA / LIQUID_MARKETS
# to be in sync) live in tests/test_coverage_registry.py so they
# only run during test execution.
validate_coverage_registry(COVERAGE_REGISTRY)
