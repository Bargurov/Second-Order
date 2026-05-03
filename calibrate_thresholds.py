"""
calibrate_thresholds.py
=======================
Empirical recalibration audit for market_check.py plausible-range guards.

Fetches 5-year rolling windows for every ticker in _PRICE_FLOORS and
_MACRO_PRICE_FLOORS, computes observed min/max/current, and compares against
the hard-coded bounds.

Run: python calibrate_thresholds.py
"""

from __future__ import annotations
import sys
import datetime
import yfinance as yf
import pandas as pd

# -- Thresholds under review (copied verbatim from market_check.py) ------------

PRICE_FLOORS = {
    "HYG":       (40.0,  120.0),
    "SHY":       (60.0,  110.0),
    "RSP":       (50.0,  300.0),
    "SPY":      (150.0,  900.0),
    "GLD":       (80.0,  400.0),
    "DX-Y.NYB":  (60.0,  150.0),
    "TLT":       (50.0,  200.0),
    "TIP":       (60.0,  160.0),
}

MACRO_PRICE_FLOORS = {
    "DXY":   ("DX-Y.NYB", 70.0,  130.0),
    "CL":    ("CL=F",     10.0,  200.0),
    "BZ=F":  ("BZ=F",     10.0,  200.0),
    "^VIX":  ("^VIX",      5.0,   90.0),
}

MACRO_MOVE_CAPS = {
    "DXY":   15.0,
    "^VIX": 200.0,
    "CL":    65.0,
    "BZ=F":  65.0,
    "10Y":    5.0,   # pp — no price guard, only move cap
}

# Signal thresholds (compute_stress_regime)
SIGNAL_THRESHOLDS = {
    "vix_elevated":          "vix_now > vix_avg20 * 1.20",
    "credit_widening":       "spread_move (SHY 5d - HYG 5d) > 0.5",
    "safe_haven_bid":        "avg_haven (GLD+DXY+TLT 5d avg) > 0.5",
    "safe_haven_inflow":     "individual asset 5d return > 0.3",
    "breadth_deterioration": "(RSP 5d - SPY 5d) < -0.5",
    "high_volume":           "vol_ratio >= 1.25",
}

# Return sanity caps
RETURN_SANITY = {
    "R1":  100.0,
    "R5":  200.0,
    "R20": 500.0,
}

# Inventory context thresholds
INVENTORY_THRESHOLDS = {
    "_TIGHT_THRESHOLD":   3.0,
    "_COMFORT_THRESHOLD": -3.0,
}

# -- Data fetch --------------------------------------------------------------

END   = datetime.date.today()
START = END - datetime.timedelta(days=5 * 365 + 30)   # ~5 years

def fetch_stats(ticker: str) -> dict:
    """Return {min, max, current, 52w_min, 52w_max} for ticker."""
    try:
        df = yf.download(ticker, start=START.isoformat(), end=END.isoformat(),
                         auto_adjust=True, progress=False)
        closes = _get_closes(df)
        if closes.empty:
            return {}
        current = float(closes.iloc[-1])
        recent52 = closes.iloc[-252:] if len(closes) >= 252 else closes
        return {
            "min_5y":    round(float(closes.min()), 2),
            "max_5y":    round(float(closes.max()), 2),
            "min_52w":   round(float(recent52.min()), 2),
            "max_52w":   round(float(recent52.max()), 2),
            "current":   round(current, 2),
            "rows":      len(closes),
        }
    except Exception as e:
        return {"error": str(e)}


def _get_closes(df: pd.DataFrame) -> pd.Series:
    """Extract a flat 1-D Close series from a potentially MultiIndex yfinance DataFrame."""
    if df is None or df.empty:
        return pd.Series(dtype=float)
    col = df["Close"]
    # yfinance sometimes returns MultiIndex when downloading a single ticker
    if isinstance(col, pd.DataFrame):
        col = col.iloc[:, 0]
    return col.dropna().astype(float)


def fetch_5d_returns(ticker: str, periods: int = 252) -> list[float]:
    """Return list of rolling 5-trading-day percent returns over the last `periods` bars."""
    try:
        df = yf.download(ticker, start=START.isoformat(), end=END.isoformat(),
                         auto_adjust=True, progress=False)
        closes = _get_closes(df)
        if len(closes) < 6:
            return []
        rets = ((closes / closes.shift(5)) - 1) * 100
        rets = rets.dropna()
        return [round(float(r), 3) for r in rets.iloc[-periods:]]
    except Exception:
        return []


# -- Report ------------------------------------------------------------------

PASS  = "[PASS]"
WARN  = "[WARN]"
FAIL  = "[FAIL]"

def check_bounds(label: str, stats: dict, lo: float, hi: float) -> str:
    if not stats or "error" in stats:
        return f"  {label:20s}  DATA_ERROR — {stats.get('error','?')}"

    issues = []
    flag = PASS
    cur = stats["current"]
    mx5  = stats["max_5y"]
    mn5  = stats["min_5y"]
    mx52 = stats["max_52w"]
    mn52 = stats["min_52w"]

    # Current price outside guard
    if not (lo <= cur <= hi):
        issues.append(f"CURRENT {cur} OUTSIDE [{lo}, {hi}]")
        flag = FAIL

    # 5-year max close to or above upper bound (within 10%)
    if mx5 > hi * 0.90 and flag != FAIL:
        issues.append(f"5y-high {mx5} within 10% of upper bound {hi}")
        flag = WARN

    # 5-year min close to or below lower bound (within 20%)
    if mn5 < lo * 1.20 and flag != FAIL:
        issues.append(f"5y-low {mn5} within 20% of lower bound {lo}")
        flag = WARN

    issue_str = "; ".join(issues) if issues else "in range"
    return (
        f"  {flag}  {label:20s}  cur={cur:>8.2f}  "
        f"5y=[{mn5:.2f}, {mx5:.2f}]  "
        f"52w=[{mn52:.2f}, {mx52:.2f}]  "
        f"guard=[{lo}, {hi}]  "
        f"→ {issue_str}"
    )


def pct_ile(data: list[float], p: float) -> float:
    import statistics
    if not data:
        return float("nan")
    s = sorted(data)
    idx = (len(s) - 1) * p / 100
    lo_i, hi_i = int(idx), min(int(idx) + 1, len(s) - 1)
    return round(s[lo_i] + (s[hi_i] - s[lo_i]) * (idx - lo_i), 3)


# -- Main --------------------------------------------------------------------─

def main():
    print(f"\n{'='*80}")
    print(f"  THRESHOLD CALIBRATION REPORT — {END.isoformat()}")
    print(f"  5-year window: {START.isoformat()} to {END.isoformat()}")
    print(f"{'='*80}\n")

    # -- 1. _PRICE_FLOORS ----------------------------------------------------─
    print("-- 1. PRICE FLOORS (_PRICE_FLOORS / _validated_pct) ----------------------─")
    issues_price: list[str] = []
    for ticker, (lo, hi) in PRICE_FLOORS.items():
        stats = fetch_stats(ticker)
        line = check_bounds(ticker, stats, lo, hi)
        print(line)
        if FAIL in line or WARN in line:
            issues_price.append(ticker)

    # -- 2. _MACRO_PRICE_FLOORS ----------------------------------------------─
    print("\n-- 2. MACRO PRICE FLOORS (_MACRO_PRICE_FLOORS / macro_snapshot) ----------")
    for key, (yticker, lo, hi) in MACRO_PRICE_FLOORS.items():
        stats = fetch_stats(yticker)
        line = check_bounds(f"{key} ({yticker})", stats, lo, hi)
        print(line)

    # -- 3. _RETURN_SANITY caps ------------------------------------------------
    print("\n-- 3. RETURN SANITY CAPS (_sanitize_returns) ----------------------------")
    print("  Checking if 5-year SPY/GLD/TLT actual 5d returns approach cap (200%)...")
    for ticker, label in [("SPY", "SPY (cap-weight)"), ("GLD", "GLD (gold)"), ("TLT", "TLT (LT bond)")]:
        rets5 = fetch_5d_returns(ticker)
        if not rets5:
            print(f"  {ticker}: no data")
            continue
        mx_abs = max(abs(r) for r in rets5)
        p99    = pct_ile([abs(r) for r in rets5], 99)
        flag = FAIL if p99 > RETURN_SANITY["R5"] * 0.5 else (WARN if p99 > RETURN_SANITY["R5"] * 0.3 else PASS)
        verdict = "OK" if flag == PASS else "watch"
        print(f"  {flag}  {label:24s}  5d max_abs={mx_abs:.2f}%  p99_abs={p99:.2f}%  "
              f"cap={RETURN_SANITY['R5']}%  -> {verdict}")

    # -- 4. VIX signal threshold -----------------------------------------------
    print("\n-- 4. VIX SIGNAL THRESHOLD (vix_now > vix_avg20 * 1.20) ----------------")
    try:
        vix_df = yf.download("^VIX", start=START.isoformat(), end=END.isoformat(),
                              auto_adjust=True, progress=False)
        vc = _get_closes(vix_df)
        if not vc.empty and len(vc) >= 20:
            current_vix = float(vc.iloc[-1])
            avg20 = float(vc.iloc[-20:].mean())
            ratio = current_vix / avg20 if avg20 else 1.0
            window20 = vc.rolling(20).mean()
            elevated = int((vc > window20 * 1.20).sum())
            fire_rate_pct = elevated / len(vc) * 100
            print(f"  Current VIX: {current_vix:.1f}  20d avg: {avg20:.1f}  ratio: {ratio:.2f}")
            print(f"  Signal fire rate (5y): {fire_rate_pct:.1f}% of trading days  (n={len(vc)})")
            status = "OK -- not too noisy" if fire_rate_pct < 35 else "NOISY -- fires too often"
            print(f"  -> Threshold 1.20x is {status}")
        else:
            print("  VIX data insufficient")
    except Exception as e:
        print(f"  VIX fetch error: {e}")

    # -- 5. Credit widening threshold (SHY-HYG 5d spread > 0.5pp) ------------
    print("\n-- 5. CREDIT WIDENING SIGNAL (SHY 5d - HYG 5d > 0.5pp) ----------------")
    try:
        hyg_rets = fetch_5d_returns("HYG")
        shy_rets = fetch_5d_returns("SHY")
        if hyg_rets and shy_rets:
            n = min(len(hyg_rets), len(shy_rets))
            spreads = [s - h for s, h in zip(shy_rets[-n:], hyg_rets[-n:])]
            fire_rate = sum(1 for s in spreads if s > 0.5) / len(spreads) * 100
            p95 = pct_ile(spreads, 95)
            p99 = pct_ile(spreads, 99)
            print(f"  5d spread stats (n={n}): p95={p95:.2f}pp  p99={p99:.2f}pp")
            print(f"  Signal fire rate: {fire_rate:.1f}% of 5d windows")
            verdict = "OK" if fire_rate < 20 else "too sensitive"
            print(f"  -> Threshold 0.5pp {verdict}")
        else:
            print("  HYG/SHY data insufficient")
    except Exception as e:
        print(f"  Credit spread fetch error: {e}")

    # -- 6. Safe-haven threshold (avg 5d return > 0.5pp) ----------------------
    print("\n-- 6. SAFE-HAVEN SIGNAL (avg GLD+DXY+TLT 5d > 0.5pp) ------------------")
    try:
        haven_data = {}
        for sym in ["GLD", "DX-Y.NYB", "TLT"]:
            haven_data[sym] = fetch_5d_returns(sym)
        lengths = [len(v) for v in haven_data.values() if v]
        if lengths:
            n = min(lengths)
            avgs = [
                sum(haven_data[s][-n:][i] for s in ["GLD", "DX-Y.NYB", "TLT"]) / 3
                for i in range(n)
            ]
            fire_rate = sum(1 for a in avgs if a > 0.5) / len(avgs) * 100
            p95 = pct_ile(avgs, 95)
            print(f"  Avg haven 5d stats (n={n}): p95={p95:.2f}pp  fire_rate={fire_rate:.1f}%")
            verdict = "OK" if fire_rate < 25 else "too sensitive"
            print(f"  -> Threshold 0.5pp {verdict}")
        else:
            print("  Haven data insufficient")
    except Exception as e:
        print(f"  Haven fetch error: {e}")

    # -- 7. Breadth gap threshold (RSP-SPY 5d < -0.5pp) ----------------------
    print("\n-- 7. BREADTH GAP SIGNAL (RSP 5d - SPY 5d < -0.5pp) -------------------")
    try:
        rsp_rets = fetch_5d_returns("RSP")
        spy_rets = fetch_5d_returns("SPY")
        if rsp_rets and spy_rets:
            n = min(len(rsp_rets), len(spy_rets))
            gaps = [r - s for r, s in zip(rsp_rets[-n:], spy_rets[-n:])]
            fire_rate = sum(1 for g in gaps if g < -0.5) / len(gaps) * 100
            p5 = pct_ile(gaps, 5)
            print(f"  RSP-SPY 5d gap (n={n}): p5={p5:.2f}pp  fire_rate={fire_rate:.1f}%")
            verdict = "OK" if fire_rate < 25 else "too sensitive"
            print(f"  -> Threshold -0.5pp {verdict}")
        else:
            print("  RSP/SPY data insufficient")
    except Exception as e:
        print(f"  Breadth fetch error: {e}")

    # -- 8. Inventory context thresholds (_TIGHT / _COMFORT = +-3%) ----------
    print("\n-- 8. INVENTORY CONTEXT (USO/XLE 20d return +/-3%) ---------------------")
    try:
        for ticker, label in [("USO", "USO (oil)"), ("XLE", "XLE (energy)")]:
            df = yf.download(ticker, start=START.isoformat(), end=END.isoformat(),
                             auto_adjust=True, progress=False)
            closes = _get_closes(df)
            if not closes.empty:
                rets20 = ((closes / closes.shift(20)) - 1) * 100
                rets20 = rets20.dropna()
                pct_tight   = float(sum(1 for r in rets20 if float(r) >  3.0)) / len(rets20) * 100
                pct_comfort = float(sum(1 for r in rets20 if float(r) < -3.0)) / len(rets20) * 100
                p95 = pct_ile([abs(float(r)) for r in rets20], 95)
                print(f"  {label:16s}: 20d ret >+3% in {pct_tight:.0f}% of bars, "
                      f"<-3% in {pct_comfort:.0f}%,  p95_abs={p95:.2f}%")
    except Exception as e:
        print(f"  Inventory fetch error: {e}")

    print(f"\n{'='*80}")
    print("  SUMMARY -- items requiring attention:")
    print(f"{'='*80}")
    print("  Review the WARN/FAIL lines above.")
    print()


if __name__ == "__main__":
    main()
