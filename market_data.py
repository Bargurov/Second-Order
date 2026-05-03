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
import threading
import time as _time
from datetime import date as _date, timedelta as _timedelta
from typing import Optional, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

_log = logging.getLogger("second_order.market_data")

# Module-level provider lock — yfinance's underlying session and
# global cache are NOT safe for concurrent calls.  Worker threads
# in market_check / price_cache that hammer ``provider.fetch_daily``
# from a ThreadPoolExecutor have been observed to receive
# cross-contaminated DataFrames (one ticker's bars persisted under
# another ticker's symbol in the SQLite price cache).  Wrapping the
# provider call in this lock serialises only the network/yfinance
# step; cache reads still run in parallel, so the hot path is
# unaffected.  Cold-cache fetches degrade to serial — slow but
# correct.  See ``macro_snapshot`` in market_check.py for the same
# rationale on the macro snapshot path.
_PROVIDER_FETCH_LOCK = threading.Lock()


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
            # timeout= caps how long a single download blocks waiting
            # for a stalled network connection.  Supported by yfinance
            # 0.2+ (the version in use).  Serialise the call to prevent
            # cross-contamination of DataFrames from concurrent threads.
            kwargs = {
                "interval": "1d", "progress": False,
                "auto_adjust": auto_adjust, "timeout": _YFINANCE_TIMEOUT,
            }
            with _PROVIDER_FETCH_LOCK:
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
_POLYGON_TIMEOUT = 10           # seconds per HTTP attempt
_POLYGON_MAX_RETRIES = 3        # total attempts (1 initial + 2 retries)
_POLYGON_RETRY_BACKOFF_BASE = 0.5  # first sleep duration in seconds; doubles each retry

# yfinance download timeout — passed directly to yf.download(timeout=N).
# Bounds the time spent waiting on a single network call.
_YFINANCE_TIMEOUT = 30          # seconds


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
        """GET a Polygon endpoint and return parsed JSON, or None on error.

        Retries up to ``_POLYGON_MAX_RETRIES`` times on transient network
        failures (URLError, unexpected exceptions) with exponential backoff.
        HTTP errors and parse errors are not retried — they are authoritative
        or unrecoverable and the fallback provider is the right escape valve.
        """
        query = dict(params or {})
        query["apiKey"] = self._api_key
        url = f"{_POLYGON_BASE}{path}?{urlencode(query)}"
        req = Request(url, headers={"User-Agent": "second-order/1.0"})

        for attempt in range(_POLYGON_MAX_RETRIES):
            if attempt > 0:
                sleep_s = _POLYGON_RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                _log.info(
                    "Polygon retry %d/%d for %s (backoff %.1fs)",
                    attempt, _POLYGON_MAX_RETRIES, path, sleep_s,
                )
                _time.sleep(sleep_s)
            try:
                with urlopen(req, timeout=_POLYGON_TIMEOUT) as resp:
                    body = resp.read().decode("utf-8")
                return json.loads(body)
            except HTTPError as e:
                # Authoritative server response — don't retry.
                _log.warning("Polygon HTTP %d for %s", e.code, path)
                return None
            except (json.JSONDecodeError, ValueError) as e:
                # Malformed response — not a transient network issue.
                _log.warning("Polygon response parse error for %s: %s", path, e)
                return None
            except Exception as e:
                # Covers URLError (network failures, timeouts) and anything
                # else unexpected.  All are worth retrying within budget.
                _log.warning(
                    "Polygon transient error for %s (attempt %d/%d): %s",
                    path, attempt + 1, _POLYGON_MAX_RETRIES, e,
                )

        _log.warning("Polygon gave up on %s after %d attempts", path, _POLYGON_MAX_RETRIES)
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

        # Guard: yfinance-specific symbol conventions are not supported by
        # Polygon's equities API.  Reject early so macro/stress paths fall
        # back to yfinance without burning free-tier Polygon quota on a
        # request that will always return zero rows.
        #
        #   ^VIX, ^TNX, ^GSPC  — CBOE / Yahoo index convention (caret-prefixed)
        #   CL=F, BZ=F, GC=F   — futures contracts (=F suffix)
        #   EURUSD=X, DX-Y.NYB — forex pairs as yfinance encodes them (=X suffix)
        if ticker.startswith("^"):
            _log.warning(
                "PolygonProvider.fetch_daily(%s): skipped — "
                "caret-prefixed index tickers are not supported by Polygon",
                ticker,
            )
            return None
        _upper = ticker.upper()
        if _upper.endswith("=F"):
            _log.warning(
                "PolygonProvider.fetch_daily(%s): skipped — "
                "futures tickers (=F suffix) are not supported by Polygon",
                ticker,
            )
            return None
        if _upper.endswith("=X"):
            _log.warning(
                "PolygonProvider.fetch_daily(%s): skipped — "
                "forex tickers (=X suffix) are not supported by Polygon",
                ticker,
            )
            return None

        try:
            start_iso, end_iso = self._resolve_range(period, start, end)
        except ValueError as e:
            _log.warning("PolygonProvider.fetch_daily(%s): bad date input: %s", ticker, e)
            return None

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
# Fallback provider — tries primary, falls back to secondary on failure
# ---------------------------------------------------------------------------

class FallbackProvider:
    """Wraps a primary and secondary provider with automatic failover.

    ``fetch_daily`` tries the primary; on ``None`` result it retries
    with the secondary (if available).  The last successful source is
    recorded in ``last_source`` so callers can surface which path
    served the data.

    ``fetch_info`` follows the same pattern.

    Thread-safe: ``last_source`` is written atomically (single string
    assignment) and is advisory — a stale read is harmless.
    """

    def __init__(
        self,
        primary: MarketDataProvider,
        secondary: MarketDataProvider | None = None,
    ):
        self.primary = primary
        self.secondary = secondary
        self.last_source: str = "primary"

    def fetch_daily(
        self,
        ticker: str,
        *,
        period: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        auto_adjust: bool = True,
    ) -> Optional[pd.DataFrame]:
        result = self.primary.fetch_daily(
            ticker, period=period, start=start, end=end,
            auto_adjust=auto_adjust,
        )
        if result is not None:
            self.last_source = "primary"
            return result

        if self.secondary is None:
            return None

        _log.info(
            "FallbackProvider: primary returned None for %s, trying secondary",
            ticker,
        )
        result = self.secondary.fetch_daily(
            ticker, period=period, start=start, end=end,
            auto_adjust=auto_adjust,
        )
        if result is not None:
            self.last_source = "fallback"
        return result

    def fetch_info(self, ticker: str) -> dict:
        info = self.primary.fetch_info(ticker)
        if info.get("name") is not None:
            self.last_source = "primary"
            return info

        if self.secondary is None:
            return info

        _log.info(
            "FallbackProvider: primary info empty for %s, trying secondary",
            ticker,
        )
        fallback_info = self.secondary.fetch_info(ticker)
        if fallback_info.get("name") is not None:
            self.last_source = "fallback"
            return fallback_info
        return info


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

def _build_default_provider() -> MarketDataProvider:
    """Build the default provider from env vars.

    MARKET_DATA_PROVIDER=polygon → FallbackProvider(Polygon primary, YFinance secondary)
    Anything else (or unset)     → plain YFinanceProvider

    Polygon only participates when explicitly requested.  A bare
    POLYGON_API_KEY without MARKET_DATA_PROVIDER=polygon does NOT
    activate Polygon — the key is available for get_secondary_provider()
    but the default path is always YFinance.
    """
    requested = (os.environ.get("MARKET_DATA_PROVIDER") or "yfinance").strip().lower()
    polygon_key = os.environ.get("POLYGON_API_KEY", "").strip()

    if requested == "polygon":
        if not polygon_key:
            _log.warning(
                "MARKET_DATA_PROVIDER=polygon but POLYGON_API_KEY is not set; "
                "falling back to YFinanceProvider"
            )
            return YFinanceProvider()
        _log.info("Using PolygonProvider for market data")
        return PolygonProvider(api_key=polygon_key)

    if requested not in ("yfinance", ""):
        _log.warning(
            "Unknown MARKET_DATA_PROVIDER=%r; falling back to YFinanceProvider",
            requested,
        )

    # Default: plain YFinanceProvider.  Polygon only participates when
    # explicitly requested via MARKET_DATA_PROVIDER=polygon.
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


def get_secondary_provider() -> "MarketDataProvider | None":
    """Return a provider different from the active one, or None.

    Used for dual-source verification: if the primary is YFinance and a
    Polygon API key is configured, returns a PolygonProvider.  If the
    primary is Polygon, returns YFinance.  Returns None when only one
    provider is available.
    """
    primary = _provider
    if isinstance(primary, YFinanceProvider):
        api_key = os.environ.get("POLYGON_API_KEY", "").strip()
        if api_key:
            return PolygonProvider(api_key=api_key)
        return None
    if isinstance(primary, PolygonProvider):
        return YFinanceProvider()
    return None
