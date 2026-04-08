"""
market_universe.py

Centralized liquid-market mapping.

App code refers to markets by stable internal identifiers (ES, NQ, GC, ...)
and calls resolve_symbol() to get the actual ticker for whichever provider
is currently active.  This module is the only place that knows how each
market maps to a yfinance vs Polygon symbol.

Why separate from market_data.py?
  market_data.py owns the *protocol* and the *adapters*.
  market_universe.py owns the *symbol catalogue* — the business knowledge
  about which liquid markets matter and how to ask each provider for them.

Design notes:
  - The catalogue is a static dict — easy to read, easy to extend.
  - When a provider can't serve a market natively (e.g. Polygon free tier
    has no futures), the mapping points to the best ETF proxy.  This is
    a behaviour difference, not a bug, and is documented per-symbol.
  - resolve_symbol() returns None for unknown identifiers.  Callers can
    fall back to using the identifier as a literal symbol.
"""

from __future__ import annotations

import logging
from typing import Optional

from market_data import (
    MarketDataProvider,
    PolygonProvider,
    YFinanceProvider,
    get_provider,
)

_log = logging.getLogger("second_order.market_universe")


# ---------------------------------------------------------------------------
# Canonical liquid markets the product cares about today
# ---------------------------------------------------------------------------

LIQUID_MARKETS: tuple[str, ...] = (
    "ES",   # S&P 500 e-mini futures (or SPY proxy)
    "NQ",   # Nasdaq 100 e-mini futures (or QQQ proxy)
    "RTY",  # Russell 2000 e-mini futures (or IWM proxy)
    "CL",   # WTI crude oil futures (or USO proxy)
    "GC",   # Gold futures (or GLD proxy)
    "DXY",  # US Dollar Index (or UUP proxy)
    "2Y",   # 2-year Treasury (SHY ETF used by both providers)
    "10Y",  # 10-year Treasury yield (^TNX) or IEF ETF for Polygon
)


# Display metadata per market.  The "asset_class" field is for grouping;
# "label" is what the UI shows; "unit" is the natural unit of the value.
LIQUID_MARKET_INFO: dict[str, dict] = {
    "ES":  {"label": "S&P 500 (ES)",     "unit": "idx",   "asset_class": "equity_index"},
    "NQ":  {"label": "Nasdaq 100 (NQ)",  "unit": "idx",   "asset_class": "equity_index"},
    "RTY": {"label": "Russell 2000",     "unit": "idx",   "asset_class": "equity_index"},
    "CL":  {"label": "WTI Crude",        "unit": "$/bbl", "asset_class": "commodity"},
    "GC":  {"label": "Gold",             "unit": "$/oz",  "asset_class": "commodity"},
    "DXY": {"label": "USD Index",        "unit": "idx",   "asset_class": "currency"},
    "2Y":  {"label": "2Y Treasury",      "unit": "$",     "asset_class": "rate"},
    "10Y": {"label": "10Y Treasury",     "unit": "%",     "asset_class": "rate"},
}


# ---------------------------------------------------------------------------
# Per-provider symbol map
# ---------------------------------------------------------------------------
#
# yfinance: prefer native futures/indices where they exist.
# polygon : use ETF proxies — Polygon free tier does NOT cover futures or
#           the typical yield indices.  The proxies are the most liquid
#           ETFs that track the same exposure.
#
# A market that resolves to an ETF proxy returns price (not the underlying
# index/yield level) — semantics matter when you compare values across
# providers.  See LIQUID_MARKET_INFO[*]["unit"].

_PROVIDER_SYMBOLS: dict[str, dict[str, str]] = {
    "yfinance": {
        "ES":  "ES=F",
        "NQ":  "NQ=F",
        "RTY": "RTY=F",
        "CL":  "CL=F",
        "GC":  "GC=F",
        "DXY": "DX-Y.NYB",
        "2Y":  "SHY",       # SHY ETF — yfinance has no clean 2Y yield symbol
        "10Y": "^TNX",
    },
    "polygon": {
        "ES":  "SPY",
        "NQ":  "QQQ",
        "RTY": "IWM",
        "CL":  "USO",
        "GC":  "GLD",
        "DXY": "UUP",
        "2Y":  "SHY",
        "10Y": "IEF",
    },
}


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def _provider_kind(provider: Optional[MarketDataProvider] = None) -> str:
    """Return 'polygon' or 'yfinance' for the given (or active) provider.

    Anything that isn't a recognised PolygonProvider falls through to the
    yfinance map — that's the safe default and matches existing behaviour.
    """
    p = provider if provider is not None else get_provider()
    if isinstance(p, PolygonProvider):
        return "polygon"
    return "yfinance"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_symbol(
    market: str,
    *,
    provider: Optional[MarketDataProvider] = None,
) -> Optional[str]:
    """Resolve a liquid market identifier to a provider-specific ticker.

    Returns None when the identifier is not a known liquid market.  The
    caller can then treat the identifier as a literal symbol or skip it.

    >>> resolve_symbol("ES")    # under YFinance
    'ES=F'
    >>> resolve_symbol("UNKNOWN")
    None
    """
    if not market:
        return None
    key = market.upper()
    if key not in LIQUID_MARKET_INFO:
        return None
    kind = _provider_kind(provider)
    sym = _PROVIDER_SYMBOLS.get(kind, {}).get(key)
    if sym is None:
        _log.warning("No %s mapping for liquid market %s", kind, key)
    return sym


def fetch_market_daily(
    market: str,
    *,
    period: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    auto_adjust: bool = True,
):
    """Fetch daily data for a liquid market via the active provider.

    Returns a DataFrame on success or None on failure / unknown market.
    Never raises — graceful degradation is the contract.
    """
    sym = resolve_symbol(market)
    if sym is None:
        _log.warning("fetch_market_daily: unknown or unmapped market %r", market)
        return None
    try:
        return get_provider().fetch_daily(
            sym, period=period, start=start, end=end, auto_adjust=auto_adjust,
        )
    except Exception as e:
        _log.warning("fetch_market_daily(%s -> %s) failed: %s", market, sym, e)
        return None


def fetch_market_info(market: str) -> Optional[dict]:
    """Return resolved metadata for a liquid market.

    Shape: {market, symbol, label, unit, asset_class}
    Returns None if the market is unknown.
    """
    if not market:
        return None
    key = market.upper()
    if key not in LIQUID_MARKET_INFO:
        return None
    info = dict(LIQUID_MARKET_INFO[key])
    info["market"] = key
    info["symbol"] = resolve_symbol(key)
    return info


def list_markets() -> list[dict]:
    """Return a list of all liquid markets with their resolved symbols."""
    return [fetch_market_info(m) for m in LIQUID_MARKETS]
