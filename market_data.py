"""
market_data.py

Minimal seam between the app and a market-data backend.

This module exposes:
  - MarketDataProvider: a Protocol describing the methods the rest of the
    application needs from any market-data source.
  - YFinanceProvider:   the default adapter, wrapping the yfinance library.
  - PolygonProvider:    optional adapter for Polygon.io REST API.
  - get_provider():     module-level accessor returning the active provider.
  - set_provider():     swap the provider (used in tests).

Provider selection happens at import time via two env vars:
  MARKET_DATA_PROVIDER  — "yfinance" (default) or "polygon"
  POLYGON_API_KEY       — required when MARKET_DATA_PROVIDER=polygon

If polygon is requested but the key is missing, the module logs a warning
and silently falls back to YFinanceProvider so existing flows keep working.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date as _date, timedelta as _timedelta
from typing import Optional, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

_log = logging.getLogger("second_order.market_data")


# ---------------------------------------------------------------------------
# Protocol — the minimum interface every provider must satisfy
# ---------------------------------------------------------------------------

@runtime_checkable
class MarketDataProvider(Protocol):
    """Tiny interface for swapping market-data backends.

    All time-series methods return a pandas DataFrame with at least:
      - DatetimeIndex (business days, ascending)
      - "Close" column (float64) — price in instrument's native units
      - "Volume" column (float64) — may be 0 for indices/futures

    Any method may return None when the ticker is unknown or no data is
    available for the requested range.  Implementations must NOT raise on
    network failures; they must log the error and return None instead.
    """

    def fetch_daily(
        self,
        ticker: str,
        *,
        period: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        auto_adjust: bool = True,
    ) -> Optional[pd.DataFrame]:
        """Fetch daily OHLCV bars.

        Pass either ``period`` (e.g. "3mo") for trailing data, or ``start``
        (with optional ``end``, defaults to today) for an explicit range.

        ``auto_adjust=True`` (default) returns split-and-dividend-adjusted
        closes — appropriate for live/rolling analysis.  Pass False for
        backtest/event-anchored fetches that need raw closes to avoid
        retroactive adjustment lookahead.
        """
        ...

    def fetch_info(self, ticker: str) -> dict:
        """Return compact instrument metadata.

        Required keys (any may be None):
          symbol, name, sector, industry, market_cap, avg_volume
        """
        ...


# ---------------------------------------------------------------------------
# Default adapter — wraps yfinance
# ---------------------------------------------------------------------------

class YFinanceProvider:
    """Default market-data provider backed by the yfinance library.

    All yfinance calls are localised here.  The rest of the codebase
    depends on the MarketDataProvider Protocol, not on yfinance directly.
    """

    def fetch_daily(
        self,
        ticker: str,
        *,
        period: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        auto_adjust: bool = True,
    ) -> Optional[pd.DataFrame]:
        if not period and not start:
            raise ValueError("fetch_daily requires either period or start")

        try:
            import yfinance as yf
        except ImportError:
            _log.error("yfinance is not installed; YFinanceProvider cannot fetch %s", ticker)
            return None

        try:
            kwargs = {"interval": "1d", "progress": False, "auto_adjust": auto_adjust}
            if period:
                data = yf.download(ticker, period=period, **kwargs)
            else:
                if end:
                    data = yf.download(ticker, start=start, end=end, **kwargs)
                else:
                    data = yf.download(ticker, start=start, **kwargs)
        except Exception as e:
            _log.warning("YFinanceProvider.fetch_daily(%s) failed: %s", ticker, e)
            return None

        if data is None or data.empty:
            return None

        # Flatten yfinance's MultiIndex columns when present
        if hasattr(data.columns, "levels"):
            data.columns = data.columns.get_level_values(0)

        # Some unadjusted requests come back without "Close" but with "Adj Close".
        if "Close" not in data.columns and "Adj Close" in data.columns:
            data["Close"] = data["Adj Close"]

        return data

    def fetch_info(self, ticker: str) -> dict:
        fallback: dict = {
            "symbol": ticker.upper(),
            "name": None, "sector": None, "industry": None,
            "market_cap": None, "avg_volume": None,
        }
        try:
            import yfinance as yf
        except ImportError:
            _log.error("yfinance is not installed; YFinanceProvider cannot fetch info for %s", ticker)
            return fallback

        try:
            t = yf.Ticker(ticker)
            info = t.info or {}
            return {
                "symbol": ticker.upper(),
                "name": info.get("longName") or info.get("shortName"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "market_cap": info.get("marketCap"),
                "avg_volume": info.get("averageVolume"),
            }
        except Exception as e:
            _log.warning("YFinanceProvider.fetch_info(%s) failed: %s", ticker, e)
            return fallback


# ---------------------------------------------------------------------------
# Polygon.io adapter
# ---------------------------------------------------------------------------

# Map yfinance-style period strings to approximate calendar-day deltas.
# Polygon does not have a "period" concept, so we convert to a date range.
_POLYGON_PERIOD_DAYS: dict[str, int] = {
    "1mo": 31, "3mo": 93, "6mo": 186, "1y": 365, "2y": 730, "5y": 1825,
}

_POLYGON_BASE = "https://api.polygon.io"
_POLYGON_TIMEOUT = 10  # seconds


class PolygonProvider:
    """Optional market-data provider backed by Polygon.io REST API.

    Uses urllib from the standard library so no extra dependency is added.
    Free-tier rate limit is 5 calls/min — the existing in-memory cache in
    market_check.py absorbs repeated calls within the TTL window.
    """

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("PolygonProvider requires a non-empty api_key")
        self._api_key = api_key

    # -- internal HTTP helper -------------------------------------------------

    def _get(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        """GET a Polygon endpoint and return parsed JSON, or None on error."""
        query = dict(params or {})
        query["apiKey"] = self._api_key
        url = f"{_POLYGON_BASE}{path}?{urlencode(query)}"
        try:
            req = Request(url, headers={"User-Agent": "second-order/1.0"})
            with urlopen(req, timeout=_POLYGON_TIMEOUT) as resp:
                body = resp.read().decode("utf-8")
            return json.loads(body)
        except HTTPError as e:
            _log.warning("Polygon HTTP %d for %s", e.code, path)
            return None
        except URLError as e:
            _log.warning("Polygon network error for %s: %s", path, e.reason)
            return None
        except (json.JSONDecodeError, ValueError) as e:
            _log.warning("Polygon response parse error for %s: %s", path, e)
            return None
        except Exception as e:
            _log.warning("Polygon unexpected error for %s: %s", path, e)
            return None

    # -- date-range helpers ---------------------------------------------------

    @staticmethod
    def _resolve_range(
        period: Optional[str], start: Optional[str], end: Optional[str],
    ) -> tuple[str, str]:
        """Return (start_iso, end_iso) for the daily aggregates request."""
        today = _date.today()
        end_date = _date.fromisoformat(end) if end else today
        if period:
            days = _POLYGON_PERIOD_DAYS.get(period, 93)
            start_date = end_date - _timedelta(days=days)
        elif start:
            start_date = _date.fromisoformat(start)
        else:
            raise ValueError("fetch_daily requires either period or start")
        return start_date.isoformat(), end_date.isoformat()

    # -- public interface -----------------------------------------------------

    def fetch_daily(
        self,
        ticker: str,
        *,
        period: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        auto_adjust: bool = True,
    ) -> Optional[pd.DataFrame]:
        if not period and not start:
            raise ValueError("fetch_daily requires either period or start")

        try:
            start_iso, end_iso = self._resolve_range(period, start, end)
        except ValueError as e:
            _log.warning("PolygonProvider.fetch_daily(%s): bad date input: %s", ticker, e)
            return None

        # Polygon symbols use '.' for class shares (e.g. BRK.B), no caret prefix
        # for indices.  We pass the ticker through as-is — caller should already
        # have a valid Polygon symbol.  Indices like ^VIX are not supported and
        # will return no results, which we surface as None.
        path = f"/v2/aggs/ticker/{ticker}/range/1/day/{start_iso}/{end_iso}"
        params = {
            "adjusted": "true" if auto_adjust else "false",
            "sort": "asc",
            "limit": 50000,
        }
        payload = self._get(path, params)
        if not payload:
            return None

        results = payload.get("results")
        if not results:
            return None

        # Polygon row: {t: ms epoch, o, h, l, c, v, vw, n}
        rows = []
        index = []
        for r in results:
            ts = r.get("t")
            close = r.get("c")
            volume = r.get("v")
            if ts is None or close is None:
                continue
            index.append(pd.Timestamp(ts, unit="ms"))
            rows.append({"Close": float(close), "Volume": float(volume or 0)})

        if not rows:
            return None

        df = pd.DataFrame(rows, index=pd.DatetimeIndex(index))
        return df

    def fetch_info(self, ticker: str) -> dict:
        fallback: dict = {
            "symbol": ticker.upper(),
            "name": None, "sector": None, "industry": None,
            "market_cap": None, "avg_volume": None,
        }
        path = f"/v3/reference/tickers/{ticker.upper()}"
        payload = self._get(path)
        if not payload:
            return fallback

        result = payload.get("results") or {}
        if not result:
            return fallback

        # Polygon does not expose averageVolume on the reference endpoint.
        # We leave it as None and let the caller fall back to a snapshot
        # query if needed (not used by the app today).
        return {
            "symbol": ticker.upper(),
            "name": result.get("name"),
            "sector": result.get("sic_description"),
            "industry": result.get("type"),
            "market_cap": result.get("market_cap"),
            "avg_volume": None,
        }


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

def _build_default_provider() -> MarketDataProvider:
    """Build the default provider from env vars.

    MARKET_DATA_PROVIDER=polygon → PolygonProvider (requires POLYGON_API_KEY)
    Anything else (or unset)     → YFinanceProvider
    """
    requested = (os.environ.get("MARKET_DATA_PROVIDER") or "yfinance").strip().lower()
    if requested == "polygon":
        api_key = os.environ.get("POLYGON_API_KEY", "").strip()
        if not api_key:
            _log.warning(
                "MARKET_DATA_PROVIDER=polygon but POLYGON_API_KEY is not set; "
                "falling back to YFinanceProvider"
            )
            return YFinanceProvider()
        _log.info("Using PolygonProvider for market data")
        return PolygonProvider(api_key=api_key)
    if requested not in ("yfinance", ""):
        _log.warning(
            "Unknown MARKET_DATA_PROVIDER=%r; falling back to YFinanceProvider",
            requested,
        )
    return YFinanceProvider()


# ---------------------------------------------------------------------------
# Module-level provider singleton
# ---------------------------------------------------------------------------

_provider: MarketDataProvider = _build_default_provider()


def get_provider() -> MarketDataProvider:
    """Return the currently active market-data provider."""
    return _provider


def set_provider(provider: MarketDataProvider) -> None:
    """Swap the active provider.  Used by tests and future alternatives."""
    global _provider
    _provider = provider


def reload_provider_from_env() -> MarketDataProvider:
    """Re-evaluate env vars and rebuild the active provider.

    Useful in tests where MARKET_DATA_PROVIDER / POLYGON_API_KEY change
    after import.  Returns the newly active provider.
    """
    global _provider
    _provider = _build_default_provider()
    return _provider
