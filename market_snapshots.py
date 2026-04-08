"""
market_snapshots.py

Lightweight background refresh layer for the liquid markets defined in
market_universe.py.

What it does:
  - Periodically refreshes the 8 liquid markets (ES, NQ, RTY, CL, GC, DXY,
    2Y, 10Y) via the active MarketDataProvider.
  - Each refresh calls the existing market_check._fetch() so the warm
    DataFrame lands in _TICKER_CACHE — interactive endpoints (macro,
    movers, stress) that subsequently call _fetch() with the same symbol
    return instantly from cache instead of making a cold provider call.
  - In parallel, builds a structured SnapshotStore with value, change_1d,
    change_5d, fetched_at, source, and a stale flag — exposed via the
    new /snapshots API endpoint for direct consumption.

Lifecycle:
  - start_background_refresh(interval) launches a daemon thread.
  - stop_background_refresh() sets a stop event and joins.
  - Disabled by default; enable in production via env var
    MARKET_SNAPSHOTS_ENABLED=true (read in api.py lifespan).

No Redis, no asyncio.  Single in-memory store, single daemon thread,
lock-protected reads/writes.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Optional

from market_data import PolygonProvider, get_provider
from market_universe import LIQUID_MARKETS, LIQUID_MARKET_INFO, resolve_symbol

_log = logging.getLogger("second_order.market_snapshots")

# How long after fetched_at a snapshot is considered fresh.  Reads beyond
# this window get a stale=True flag but the underlying data is still returned.
SNAPSHOT_MAX_AGE_SECONDS: int = 120  # 2 minutes

# Default refresh interval for the background thread.
DEFAULT_REFRESH_INTERVAL: int = 60   # 1 minute


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class MarketSnapshot:
    """A single liquid-market snapshot with freshness metadata."""

    market: str           # canonical liquid-market identifier (e.g. "ES")
    symbol: Optional[str]  # provider-specific ticker (None if unmapped)
    label: str            # display label
    unit: str             # natural unit of value
    asset_class: str      # equity_index / commodity / currency / rate
    source: str           # provider kind ("yfinance" / "polygon" / "unknown")
    value: Optional[float] = None
    change_1d: Optional[float] = None
    change_5d: Optional[float] = None
    fetched_at: Optional[str] = None  # ISO 8601 UTC string
    error: Optional[str] = None
    stale: bool = False               # set by store on read

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Snapshot store — thread-safe in-memory map keyed by liquid market id
# ---------------------------------------------------------------------------

class SnapshotStore:
    """Thread-safe in-memory store for market snapshots.

    Stores (snapshot, monotonic_timestamp) pairs.  Reads compute the stale
    flag against the current monotonic time so freshness reflects read time.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[MarketSnapshot, float]] = {}

    def update(self, snapshot: MarketSnapshot) -> None:
        with self._lock:
            self._entries[snapshot.market.upper()] = (snapshot, time.monotonic())

    def get(self, market: str) -> Optional[MarketSnapshot]:
        if not market:
            return None
        key = market.upper()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            snap, mono = entry
            stale = (time.monotonic() - mono) > SNAPSHOT_MAX_AGE_SECONDS
            return replace(snap, stale=stale)

    def all(self) -> list[MarketSnapshot]:
        with self._lock:
            now = time.monotonic()
            results: list[MarketSnapshot] = []
            for snap, mono in self._entries.values():
                stale = (now - mono) > SNAPSHOT_MAX_AGE_SECONDS
                results.append(replace(snap, stale=stale))
            # Sort by canonical market order so callers see a stable list
            order = {m: i for i, m in enumerate(LIQUID_MARKETS)}
            results.sort(key=lambda s: order.get(s.market, 999))
            return results

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


# Module-level store
_store = SnapshotStore()


def get_store() -> SnapshotStore:
    """Return the active snapshot store (mainly for tests)."""
    return _store


def get_snapshot(market: str) -> Optional[MarketSnapshot]:
    """Return a single snapshot or None if the market has not been refreshed."""
    return _store.get(market)


def get_all_snapshots() -> list[MarketSnapshot]:
    """Return all current snapshots in canonical order."""
    return _store.all()


# ---------------------------------------------------------------------------
# Provider name detection
# ---------------------------------------------------------------------------

def _provider_name() -> str:
    p = get_provider()
    if isinstance(p, PolygonProvider):
        return "polygon"
    cls = type(p).__name__
    if "YFinance" in cls or "Yfinance" in cls:
        return "yfinance"
    return cls.lower() or "unknown"


# ---------------------------------------------------------------------------
# Refresh logic
# ---------------------------------------------------------------------------

def _build_empty_snapshot(market: str, symbol: Optional[str], error: str) -> MarketSnapshot:
    info = LIQUID_MARKET_INFO[market.upper()]
    return MarketSnapshot(
        market=market.upper(),
        symbol=symbol,
        label=info["label"],
        unit=info["unit"],
        asset_class=info["asset_class"],
        source=_provider_name(),
        error=error,
    )


def refresh_market(market: str) -> Optional[MarketSnapshot]:
    """Refresh a single liquid market and store the result.

    Returns the new snapshot, or None if the market is unknown.
    Failures are stored as a snapshot with an `error` field set, never raised.
    """
    key = (market or "").upper()
    if key not in LIQUID_MARKET_INFO:
        return None

    symbol = resolve_symbol(key)
    if symbol is None:
        snap = _build_empty_snapshot(key, None, "no symbol mapping")
        _store.update(snap)
        return snap

    # Import locally to avoid any circular-import risk and to make
    # test patching of market_check._fetch / _pct work cleanly.
    import market_check

    try:
        data = market_check._fetch(symbol)
    except Exception as e:
        _log.warning("refresh_market(%s): _fetch raised: %s", key, e)
        snap = _build_empty_snapshot(key, symbol, f"fetch error: {e}")
        _store.update(snap)
        return snap

    if data is None or len(data) < 2:
        snap = _build_empty_snapshot(key, symbol, "no data")
        _store.update(snap)
        return snap

    info = LIQUID_MARKET_INFO[key]
    closes = data["Close"]
    try:
        value = round(float(closes.iloc[-1]), 2)
    except Exception as e:
        _log.warning("refresh_market(%s): value extract failed: %s", key, e)
        snap = _build_empty_snapshot(key, symbol, f"value error: {e}")
        _store.update(snap)
        return snap

    r1 = market_check._pct(closes, 1)
    r5 = market_check._pct(closes, 5)

    snap = MarketSnapshot(
        market=key,
        symbol=symbol,
        label=info["label"],
        unit=info["unit"],
        asset_class=info["asset_class"],
        source=_provider_name(),
        value=value,
        change_1d=round(r1, 2) if r1 is not None else None,
        change_5d=round(r5, 2) if r5 is not None else None,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    _store.update(snap)
    return snap


def refresh_all() -> list[MarketSnapshot]:
    """Refresh every liquid market.  Returns the list of snapshots produced.

    Errors on individual markets are isolated — one bad fetch does not
    block the others.  All resulting snapshots (success or error) are
    written to the store.
    """
    results: list[MarketSnapshot] = []
    for m in LIQUID_MARKETS:
        try:
            snap = refresh_market(m)
            if snap is not None:
                results.append(snap)
        except Exception:
            _log.exception("refresh_all: unexpected error for %s", m)
    return results


# ---------------------------------------------------------------------------
# Background daemon thread
# ---------------------------------------------------------------------------

_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_thread_lock = threading.Lock()


def is_running() -> bool:
    """Return True if the background refresh thread is currently running."""
    with _thread_lock:
        return _thread is not None and _thread.is_alive()


def start_background_refresh(interval: int = DEFAULT_REFRESH_INTERVAL) -> bool:
    """Start the daemon refresh thread.

    Returns True if a new thread was started, False if one was already running.
    """
    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return False
        _stop_event.clear()

        def _loop() -> None:
            # Refresh once immediately so the first request after startup
            # finds warm data.
            try:
                refresh_all()
            except Exception:
                _log.exception("initial snapshot refresh failed")
            while not _stop_event.is_set():
                if _stop_event.wait(interval):
                    break
                try:
                    refresh_all()
                except Exception:
                    _log.exception("snapshot refresh loop iteration failed")

        _thread = threading.Thread(
            target=_loop, daemon=True, name="snapshot-refresh",
        )
        _thread.start()
        _log.info("Background snapshot refresh started (interval=%ds)", interval)
        return True


def stop_background_refresh(timeout: float = 5.0) -> None:
    """Signal the background thread to stop and wait for it to exit."""
    global _thread
    _stop_event.set()
    with _thread_lock:
        if _thread is not None:
            _thread.join(timeout=timeout)
            _thread = None
    _log.info("Background snapshot refresh stopped")
