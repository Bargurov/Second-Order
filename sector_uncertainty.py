"""
sector_uncertainty.py

Computes 20-day realized volatility for sector ETFs versus SPY baseline.
Used to surface sector-specific uncertainty concentration in the UI.

Volatility = annualised 20-day std of daily log-returns.
vol_ratio   = sector_vol / spy_vol  (ratio >= 1.3 → elevated)
status      = "stressed" | "watch" | "calm"  (matches StressComponentDetail vocab)
concentration = "concentrated" | "mixed" | "diffuse"  (governs UI lead behaviour)
"""

import math
import logging
import statistics
import time
from typing import Optional

_log = logging.getLogger("second_order.sector_uncertainty")

# Sector ETF universe — one representative ETF per sector.
SECTOR_ETFS: dict[str, str] = {
    "Energy":        "XLE",
    "Semiconductors":"SMH",
    "Defense":       "XAR",
    "Financials":    "XLF",
    "Tech":          "XLK",
    "Healthcare":    "XLV",
    "Industrials":   "XLI",
    "Materials":     "XLB",
    "Utilities":     "XLU",
    "Real Estate":   "XLRE",
    "Consumer Disc": "XLY",
    "Consumer Stap": "XLP",
}

SPY = "SPY"
ANNUALIZE = math.sqrt(252)

# Thresholds
STRESSED_RATIO = 1.5
WATCH_RATIO    = 1.3
CONCENTRATED_COUNT = 3  # sectors elevated → concentrated
MIXED_COUNT        = 1  # ≥1 but < concentrated

# Module-level TTL cache
_CACHE: dict = {"data": None, "ts": 0.0}
_TTL = 12 * 60  # seconds (12 minutes)


def _log_returns(closes: list[float]) -> list[float]:
    """Compute daily log-returns from a list of close prices."""
    out = []
    for i in range(1, len(closes)):
        prev, curr = closes[i - 1], closes[i]
        if prev > 0 and curr > 0:
            out.append(math.log(curr / prev))
    return out


def _realized_vol(closes: list[float]) -> Optional[float]:
    """20-day annualised realised vol from a list of close prices.

    Returns None when fewer than 5 usable returns are available.
    """
    rets = _log_returns(closes)
    if len(rets) < 5:
        return None
    try:
        stdev = statistics.stdev(rets)
    except statistics.StatisticsError:
        return None
    if not math.isfinite(stdev) or stdev < 0:
        return None
    return round(stdev * ANNUALIZE * 100, 2)  # as percentage


def _closes_from_df(df) -> list[float]:
    """Extract Close column as a plain float list, dropping NaN."""
    if df is None or df.empty:
        return []
    col = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
    return [float(v) for v in col if math.isfinite(float(v))]


def _status(vol_ratio: float) -> str:
    if vol_ratio >= STRESSED_RATIO:
        return "stressed"
    if vol_ratio >= WATCH_RATIO:
        return "watch"
    return "calm"


def compute_sector_uncertainty() -> dict:
    """Return sector vol data with TTL caching.

    Shape::

        {
          "available": True,
          "spy_vol_20d": 14.2,
          "concentration": "concentrated" | "mixed" | "diffuse",
          "lead_sector": "Energy" | None,
          "sectors": [
            {"sector": "Energy", "etf": "XLE", "vol_20d": 22.1,
             "vol_ratio": 1.56, "status": "stressed"},
            ...
          ]
        }

    Returns ``{"available": False}`` when SPY data is unavailable.
    """
    now = time.monotonic()
    if _CACHE["data"] is not None and now - _CACHE["ts"] < _TTL:
        return _CACHE["data"]

    result = _compute()
    _CACHE["data"] = result
    _CACHE["ts"] = now
    return result


def _compute() -> dict:
    from price_cache import fetch_daily_cached

    # Fetch SPY first — if it fails, the whole module is unavailable.
    try:
        spy_df = fetch_daily_cached(SPY, period="3mo", auto_adjust=True)
        spy_closes = _closes_from_df(spy_df)
        spy_vol = _realized_vol(spy_closes[-21:])  # last 20 bars + 1 for returns
    except Exception:
        _log.warning("sector_uncertainty: SPY fetch failed", exc_info=True)
        return {"available": False}

    if spy_vol is None or spy_vol == 0:
        return {"available": False}

    sectors_out = []
    for sector_name, etf in SECTOR_ETFS.items():
        try:
            df = fetch_daily_cached(etf, period="3mo", auto_adjust=True)
            closes = _closes_from_df(df)
            vol = _realized_vol(closes[-21:])
            if vol is None:
                continue
            ratio = round(vol / spy_vol, 3)
            sectors_out.append({
                "sector":    sector_name,
                "etf":       etf,
                "vol_20d":   vol,
                "vol_ratio": ratio,
                "status":    _status(ratio),
            })
        except Exception:
            _log.warning("sector_uncertainty: %s fetch failed", etf, exc_info=True)
            continue

    # Sort by vol_ratio descending so the UI can render ranked chips.
    sectors_out.sort(key=lambda s: s["vol_ratio"], reverse=True)

    elevated = [s for s in sectors_out if s["vol_ratio"] >= WATCH_RATIO]
    n_elevated = len(elevated)
    if n_elevated >= CONCENTRATED_COUNT:
        concentration = "concentrated"
    elif n_elevated >= MIXED_COUNT:
        concentration = "mixed"
    else:
        concentration = "diffuse"

    lead_sector = sectors_out[0]["sector"] if sectors_out else None

    return {
        "available":    True,
        "spy_vol_20d":  spy_vol,
        "concentration": concentration,
        "lead_sector":  lead_sector,
        "sectors":      sectors_out,
    }
