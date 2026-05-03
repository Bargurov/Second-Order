"""
calibrate_thresholds_pass2.py

Second empirical calibration pass targeting thresholds in:
  - shock_decomposition._CHANNEL_SCALE  (1-sigma 5d move normalizers)
  - reaction_function_divergence        (direction scoring thresholds)
  - reserve_stress_overlay              (DXY / crude tier thresholds)
  - real_yield_context                  (alignment cutoffs + caps)
  - surprise_vs_anticipation            (VIX change thresholds)
  - terms_of_trade                      (crude / DXY trigger thresholds)

Run:
  python calibrate_thresholds_pass2.py
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import date, timedelta

END   = date.today()
START = END - timedelta(days=5 * 365 + 90)   # ~5 years + buffer

TICKERS = {
    "TNX":   "^TNX",       # 10Y nominal yield (level, not price)
    "TIP":   "TIP",        # TIPS ETF (real-yield proxy)
    "DXY":   "DX-Y.NYB",   # Dollar index
    "CL":    "CL=F",       # WTI crude
    "GC":    "GC=F",       # Gold
    "ES":    "ES=F",       # S&P 500 futures
    "VIX":   "^VIX",       # VIX level
}


# -----------------------------------------------------------------------
# Fetch helpers
# -----------------------------------------------------------------------

def _get_closes(df):
    if df is None or (hasattr(df, 'empty') and df.empty):
        return pd.Series(dtype=float)
    col = df["Close"]
    if isinstance(col, pd.DataFrame):
        col = col.iloc[:, 0]
    return col.dropna().astype(float)


def fetch(sym):
    try:
        df = yf.download(sym, start=START.isoformat(), end=END.isoformat(),
                         progress=False, auto_adjust=True)
        return _get_closes(df)
    except Exception as e:
        print(f"  WARN: could not fetch {sym}: {e}")
        return pd.Series(dtype=float)


def pct_change_5d(series):
    """5-day rolling percentage change."""
    return series.pct_change(5) * 100.0


def abs_change_5d(series):
    """5-day rolling absolute change (for yield levels)."""
    return series.diff(5)


# -----------------------------------------------------------------------
# Fetch all series
# -----------------------------------------------------------------------

print("Fetching data ...")
data = {}
for name, sym in TICKERS.items():
    s = fetch(sym)
    if len(s) > 20:
        data[name] = s
        print(f"  {name:5s} ({sym}): {len(s)} rows  "
              f"latest={s.iloc[-1]:.4f}  min={s.min():.4f}  max={s.max():.4f}")
    else:
        print(f"  {name:5s} ({sym}): NO DATA")

# Align all series to a common index
common = None
for s in data.values():
    common = s.index if common is None else common.intersection(s.index)
print(f"\nCommon trading days: {len(common)}  ({common[0].date()} -> {common[-1].date()})")


# -----------------------------------------------------------------------
# 5d move series
# -----------------------------------------------------------------------

tnx_5d   = abs_change_5d(data["TNX"].reindex(common))   if "TNX" in data else None
tip_5d   = pct_change_5d(data["TIP"].reindex(common))   if "TIP" in data else None
dxy_5d   = pct_change_5d(data["DXY"].reindex(common))   if "DXY" in data else None
cl_5d    = pct_change_5d(data["CL"].reindex(common))    if "CL"  in data else None
gc_5d    = pct_change_5d(data["GC"].reindex(common))    if "GC"  in data else None
es_5d    = pct_change_5d(data["ES"].reindex(common))    if "ES"  in data else None
vix      = data["VIX"].reindex(common) if "VIX" in data else None
vix_5d   = abs_change_5d(vix)          if vix is not None else None


def stats(s, label):
    s = s.dropna()
    if len(s) < 10:
        return f"  {label}: NO DATA"
    mu  = s.mean()
    sd  = s.std()
    p75 = s.abs().quantile(0.75)
    p90 = s.abs().quantile(0.90)
    p95 = s.abs().quantile(0.95)
    return (f"  {label:<28s}  mu={mu:+.3f}  1sigma={sd:.3f}  "
            f"p75={p75:.3f}  p90={p90:.3f}  p95={p95:.3f}  n={len(s)}")


# -----------------------------------------------------------------------
# SECTION 1 -- shock_decomposition._CHANNEL_SCALE
#
# Current scales (institutional 1-sigma 5d move normalizers):
#   nominal_yield  0.20 pp
#   real_yield     0.50 %
#   fx             0.70 %
#   commodity      3.00 %
# -----------------------------------------------------------------------

print("\n" + "=" * 70)
print("SECTION 1 -- shock_decomposition._CHANNEL_SCALE")
print("  (1-sigma of rolling 5d move = the scale value)")
print("=" * 70)

if tnx_5d is not None:
    print(stats(tnx_5d, "nominal_yield (TNX abs pp)"))
    actual_nom_sigma = tnx_5d.dropna().std()
    print(f"  current _CHANNEL_SCALE['nominal_yield'] = 0.20 pp")
    print(f"  actual  1-sigma (5y)                    = {actual_nom_sigma:.3f} pp")
    pct_diff = (actual_nom_sigma - 0.20) / 0.20 * 100
    verdict = "RAISE" if actual_nom_sigma > 0.30 else ("LOWER" if actual_nom_sigma < 0.14 else "OK")
    print(f"  diff = {pct_diff:+.0f}%  -> {verdict}")

print()
if tip_5d is not None:
    print(stats(tip_5d, "real_yield (TIP pct change)"))
    actual_tip_sigma = tip_5d.dropna().std()
    print(f"  current _CHANNEL_SCALE['real_yield'] = 0.50 %")
    print(f"  actual  1-sigma (5y)                 = {actual_tip_sigma:.3f} %")
    pct_diff = (actual_tip_sigma - 0.50) / 0.50 * 100
    verdict = "RAISE" if actual_tip_sigma > 0.75 else ("LOWER" if actual_tip_sigma < 0.35 else "OK")
    print(f"  diff = {pct_diff:+.0f}%  -> {verdict}")

print()
if dxy_5d is not None:
    print(stats(dxy_5d, "fx (DXY pct change)"))
    actual_dxy_sigma = dxy_5d.dropna().std()
    print(f"  current _CHANNEL_SCALE['fx'] = 0.70 %")
    print(f"  actual  1-sigma (5y)         = {actual_dxy_sigma:.3f} %")
    pct_diff = (actual_dxy_sigma - 0.70) / 0.70 * 100
    verdict = "RAISE" if actual_dxy_sigma > 1.05 else ("LOWER" if actual_dxy_sigma < 0.49 else "OK")
    print(f"  diff = {pct_diff:+.0f}%  -> {verdict}")

print()
if cl_5d is not None:
    print(stats(cl_5d, "commodity (CL pct change)"))
    actual_cl_sigma = cl_5d.dropna().std()
    print(f"  current _CHANNEL_SCALE['commodity'] = 3.00 %")
    print(f"  actual  1-sigma (5y)                = {actual_cl_sigma:.3f} %")
    pct_diff = (actual_cl_sigma - 3.00) / 3.00 * 100
    verdict = "RAISE" if actual_cl_sigma > 4.50 else ("LOWER" if actual_cl_sigma < 2.10 else "OK")
    print(f"  diff = {pct_diff:+.0f}%  -> {verdict}")

print()
# Breakeven proxy: nominal_pp + TIP_pct / TIP_DURATION
# Using TIP modified duration ~7.5 years (standard for this ETF)
_TIP_DURATION = 7.5
if tnx_5d is not None and tip_5d is not None:
    be_5d = tnx_5d + tip_5d / _TIP_DURATION
    be_5d_clean = be_5d.dropna()
    actual_be_sigma = be_5d_clean.std()
    print(stats(be_5d_clean, "breakeven proxy (composite pp)"))
    print(f"  current _CHANNEL_SCALE['breakeven'] = 0.20 pp")
    print(f"  actual  1-sigma (5y)                = {actual_be_sigma:.3f} pp")
    pct_diff = (actual_be_sigma - 0.20) / 0.20 * 100
    verdict = "RAISE" if actual_be_sigma > 0.30 else ("LOWER" if actual_be_sigma < 0.14 else "OK")
    print(f"  diff = {pct_diff:+.0f}%  -> {verdict}")


# -----------------------------------------------------------------------
# SECTION 2 -- reaction_function_divergence direction thresholds
#
# Current thresholds:
#   nom_5d > 0.3 pp  -> hawk +2   (also < -0.3 -> dove +2)
#   real_5d < -0.4 % -> hawk +2   (TIP fell = real yields rose)
#   real_5d > +0.4 % -> dove +2
#   be_5d  > 0.3 pp  -> hawk +1   (be_5d < -0.3 -> dove +1)
#   dxy_5d > 1.0 %   -> hawk +1   (dxy_5d < -1.0 -> dove +1)
#   es_5d  < -2.0 %  -> dove +1
# -----------------------------------------------------------------------

print("\n" + "=" * 70)
print("SECTION 2 -- reaction_function_divergence direction thresholds")
print("  (fire rate = % of 5d bars where the signal fires)")
print("  Target: signals should fire on ~20-30% of bars to be informative")
print("=" * 70)


def fire_rate(s, threshold, direction="above"):
    s = s.dropna()
    if len(s) == 0:
        return float("nan"), 0
    if direction == "above":
        n = (s > threshold).sum()
    elif direction == "below":
        n = (s < threshold).sum()
    else:  # abs
        n = (s.abs() > threshold).sum()
    return n / len(s) * 100, len(s)


if tnx_5d is not None:
    fr_hawk, n = fire_rate(tnx_5d, 0.3, "above")
    fr_dove, _ = fire_rate(tnx_5d, -0.3, "below")
    print(f"  TNX nom_5d >+0.3pp  (hawk+2): {fr_hawk:.1f}%  |  <-0.3pp (dove+2): {fr_dove:.1f}%  n={n}")
    print(f"    current = 0.3pp  ->  {'OK' if 15 < fr_hawk < 40 else 'CHECK'}")
    # Also show what 40th/60th pctile is for reference
    tnx_clean = tnx_5d.dropna()
    p60 = tnx_clean.quantile(0.60)
    p40 = tnx_clean.quantile(0.40)
    print(f"    p40={p40:.3f}pp  p60={p60:.3f}pp  (40-60th pctile of signed moves)")

print()
if tip_5d is not None:
    fr_hawk, n = fire_rate(tip_5d, -0.4, "below")   # TIP fell = real yields rose
    fr_dove, _ = fire_rate(tip_5d, +0.4, "above")
    print(f"  TIP real_5d < -0.4%  (hawk+2): {fr_hawk:.1f}%  |  >+0.4% (dove+2): {fr_dove:.1f}%  n={n}")
    print(f"    current = 0.4%  ->  {'OK' if 15 < fr_hawk < 40 else 'CHECK'}")
    tip_clean = tip_5d.dropna()
    p40 = tip_clean.quantile(0.40)
    p60 = tip_clean.quantile(0.60)
    print(f"    p40={p40:.3f}%  p60={p60:.3f}%")

print()
if tnx_5d is not None and tip_5d is not None:
    be_5d = (tnx_5d + tip_5d / _TIP_DURATION).dropna()
    fr_hawk, n = fire_rate(be_5d, 0.3, "above")
    fr_dove, _ = fire_rate(be_5d, -0.3, "below")
    print(f"  breakeven be_5d >+0.3pp (hawk+1): {fr_hawk:.1f}%  |  <-0.3pp (dove+1): {fr_dove:.1f}%  n={n}")
    print(f"    current = 0.3pp  ->  {'OK' if 15 < fr_hawk < 40 else 'CHECK'}")

print()
if dxy_5d is not None:
    fr_hawk, n = fire_rate(dxy_5d, 1.0, "above")
    fr_dove, _ = fire_rate(dxy_5d, -1.0, "below")
    print(f"  DXY dxy_5d >+1.0%  (hawk+1): {fr_hawk:.1f}%  |  <-1.0% (dove+1): {fr_dove:.1f}%  n={n}")
    print(f"    current = 1.0%  ->  {'OK' if 15 < fr_hawk < 40 else 'CHECK'}")
    dxy_clean = dxy_5d.dropna()
    p70 = dxy_clean.quantile(0.70)
    p30 = dxy_clean.quantile(0.30)
    print(f"    p30={p30:.3f}%  p70={p70:.3f}%")

print()
if es_5d is not None:
    fr_dove, n = fire_rate(es_5d, -2.0, "below")
    print(f"  ES es_5d < -2.0%  (dove+1): {fr_dove:.1f}%  n={n}")
    print(f"    current = -2.0%  ->  {'OK' if 10 < fr_dove < 30 else 'CHECK'}")


# -----------------------------------------------------------------------
# SECTION 3 -- reserve_stress_overlay DXY / crude thresholds
#
# Current thresholds:
#   DXY moderate >= 0.5%  -> score +15
#   DXY strong   >= 1.0%  -> score +25 (replaces moderate)
#   DXY extreme  >= 2.0%  -> score +35 (replaces strong)
#   crude moderate >= 3.0% -> score +20
#   crude strong   >= 5.0% -> score +5 (stacks)
#   credit widening >= 0.5pp -> score +20
#   real yield rise >= 0.2%  -> score +15
# -----------------------------------------------------------------------

print("\n" + "=" * 70)
print("SECTION 3 -- reserve_stress_overlay DXY / crude thresholds")
print("  (fire rate = % of 5d bars where threshold is exceeded)")
print("  DXY tiers are non-stacking; target moderate at ~40%, strong at ~20%")
print("=" * 70)

if dxy_5d is not None:
    dxy_clean = dxy_5d.dropna()
    n = len(dxy_clean)
    for thresh in [0.5, 1.0, 2.0]:
        fr = (dxy_clean.abs() >= thresh).mean() * 100
        fr_up = (dxy_clean >= thresh).mean() * 100
        print(f"  DXY |5d| >= {thresh:.1f}%: {fr:.1f}%  (directional up: {fr_up:.1f}%)  n={n}")

print()
if cl_5d is not None:
    cl_clean = cl_5d.dropna()
    n = len(cl_clean)
    for thresh in [3.0, 5.0]:
        fr = (cl_clean.abs() >= thresh).mean() * 100
        fr_up = (cl_clean >= thresh).mean() * 100
        print(f"  Crude |5d| >= {thresh:.1f}%: {fr:.1f}%  (directional up: {fr_up:.1f}%)  n={n}")

print()
if tip_5d is not None:
    # Real yield rise: TIP falls -> real yields rise, inversion: real_yield_5d = -tip_5d
    ryield_5d = -tip_5d.dropna()
    n = len(ryield_5d)
    for thresh in [0.2, 0.4]:
        fr = (ryield_5d >= thresh).mean() * 100
        print(f"  Real yield rise (TIP invert) >= {thresh:.2f}%: {fr:.1f}%  n={n}")

print()
# Also show terms_of_trade thresholds for cross-reference
if dxy_5d is not None:
    dxy_clean = dxy_5d.dropna()
    fr_strong = (dxy_clean.abs() >= 1.0).mean() * 100
    fr_moderate = (dxy_clean.abs() >= 0.5).mean() * 100
    print(f"  [terms_of_trade cross-check]")
    print(f"  DXY strong |5d| >= 1.0% fire: {fr_strong:.1f}%  current threshold OK if ~20-30%")
    print(f"  DXY moderate |5d| >= 0.5% fire: {fr_moderate:.1f}%  current threshold OK if ~40-50%")
if cl_5d is not None:
    cl_clean = cl_5d.dropna()
    fr_crude = (cl_clean.abs() >= 3.0).mean() * 100
    print(f"  Crude |5d| >= 3.0% fire: {fr_crude:.1f}%  current threshold OK if ~35-50%")


# -----------------------------------------------------------------------
# SECTION 4 -- real_yield_context alignment cutoffs + caps
#
# Alignment thresholds (confirm / tension):
#   breakeven_5d > +0.2 pp -> confirms inflationary
#   breakeven_5d < -0.2 pp -> confirms disinflationary
#   real_5d (TIP) < -0.2 % -> confirms rate_pressure_up
#   real_5d (TIP) > +0.2 % -> confirms rate_pressure_down
#
# Sanity caps (should never be exceeded in real data):
#   NOMINAL_CAP  = 5.0 pp
#   REAL_CAP     = 20.0 %  (TIP ETF price move)
#   BREAKEVEN_CAP = 7.0 pp
# -----------------------------------------------------------------------

print("\n" + "=" * 70)
print("SECTION 4 -- real_yield_context alignment cutoffs + caps")
print("=" * 70)

if tnx_5d is not None and tip_5d is not None:
    be_5d = (tnx_5d + tip_5d / _TIP_DURATION).dropna()
    fr_confirm_inf, n  = fire_rate(be_5d, 0.2, "above")
    fr_confirm_dis, _  = fire_rate(be_5d, -0.2, "below")
    print(f"  breakeven >+0.2pp (confirm inflationary): {fr_confirm_inf:.1f}%  n={n}")
    print(f"  breakeven <-0.2pp (confirm disinflation): {fr_confirm_dis:.1f}%")
    print(f"    current = 0.2pp  ->  {'OK' if 30 < fr_confirm_inf < 55 else 'CHECK'}")
    print(f"    (alignment cutoff should confirm ~30-50% of time -- not too rare, not ubiquitous)")

print()
if tip_5d is not None:
    tip_clean = tip_5d.dropna()
    fr_rate_up,  n  = fire_rate(tip_clean, -0.2, "below")   # TIP fell = real rates rose
    fr_rate_down, _ = fire_rate(tip_clean, +0.2, "above")
    print(f"  TIP < -0.2% (confirm rate_pressure_up): {fr_rate_up:.1f}%  n={n}")
    print(f"  TIP > +0.2% (confirm rate_pressure_down): {fr_rate_down:.1f}%")
    print(f"    current = 0.2%  ->  {'OK' if 30 < fr_rate_up < 60 else 'CHECK'}")

print()
# Cap validation
print("  Cap validation -- largest 5d move in 5y data:")
if tnx_5d is not None:
    max_nom = tnx_5d.dropna().abs().max()
    print(f"  nominal_yield  max |5d| = {max_nom:.3f} pp  (cap=5.0)  -> {'OK' if max_nom < 5.0 else 'BREACH'}")
if tip_5d is not None:
    max_real = tip_5d.dropna().abs().max()
    print(f"  real_yield     max |5d| = {max_real:.3f} %   (cap=20.0) -> {'OK' if max_real < 20.0 else 'BREACH'}")
if tnx_5d is not None and tip_5d is not None:
    be_5d = (tnx_5d + tip_5d / _TIP_DURATION).dropna()
    max_be = be_5d.abs().max()
    print(f"  breakeven      max |5d| = {max_be:.3f} pp  (cap=7.0)  -> {'OK' if max_be < 7.0 else 'BREACH'}")


# -----------------------------------------------------------------------
# SECTION 5 -- surprise_vs_anticipation VIX change thresholds
#
# Current thresholds:
#   vix_change_5d >= 1.5  -> surprise_shock +2
#   vix_change_5d <= -1.5 -> uncertainty_resolution +2
#   vix_change_5d <= -0.75 -> uncertainty_resolution +1
#   vix_change_5d >= 0.75  -> surprise_shock +1
# -----------------------------------------------------------------------

print("\n" + "=" * 70)
print("SECTION 5 -- surprise_vs_anticipation VIX change thresholds")
print("  (vix_change_5d = 5d absolute VIX level change)")
print("  Target: +/-1.5 fires on ~20-30% of bars")
print("=" * 70)

if vix_5d is not None:
    vix_5d_clean = vix_5d.dropna()
    n = len(vix_5d_clean)
    print(stats(vix_5d_clean, "VIX 5d abs change"))

    for thresh in [0.75, 1.5, 3.0]:
        fr_up   = (vix_5d_clean >= thresh).mean() * 100
        fr_down = (vix_5d_clean <= -thresh).mean() * 100
        print(f"  VIX 5d >= +{thresh:.2f}: {fr_up:.1f}%  |  <= -{thresh:.2f}: {fr_down:.1f}%  n={n}")
    p70 = vix_5d_clean.quantile(0.70)
    p30 = vix_5d_clean.quantile(0.30)
    p80 = vix_5d_clean.quantile(0.80)
    p20 = vix_5d_clean.quantile(0.20)
    print(f"  p20={p20:.2f}  p30={p30:.2f}  p70={p70:.2f}  p80={p80:.2f}")
    print(f"  current +/-1.5 fires: {'OK' if 20 < fr_up < 40 else 'CHECK'}")


# -----------------------------------------------------------------------
# SECTION 6 -- Summary / recommendations
# -----------------------------------------------------------------------

print("\n" + "=" * 70)
print("SECTION 6 -- Summary and recommendations")
print("=" * 70)

print("""
Thresholds to consider changing:
  (compare each verdict line in sections 1-5 above)

shock_decomposition._CHANNEL_SCALE
  - Check verdict line per channel.
  - Only update if actual 1-sigma deviates >50% from the coded value.
  - Breakeven proxy sigma is derived, may be noisier than nominal alone.

reaction_function_divergence
  - Direction thresholds should fire on ~15-35% of bars per side.
  - If nom_5d >0.3pp fires on >45% of bars, raise to 0.4pp or 0.5pp.
  - DXY >1.0% should fire ~20-25% of bars; if >35% consider 1.2-1.5%.

reserve_stress_overlay
  - DXY moderate >= 0.5%: OK if fires ~40-55% of bars (often-active signal).
  - DXY strong >= 1.0%: OK if fires ~20-30%.
  - DXY extreme >= 2.0%: OK if fires ~5-10%.
  - Crude moderate >= 3.0%: OK if fires ~35-50%.
  - These thresholds are for scoring, not for hard gating -- keep looser.

real_yield_context alignment cutoffs
  - 0.2pp breakeven / 0.2% TIP are intentionally sensitive -- they just
    need to fire 'often enough' (>30% of bars) to be confirmable.
  - If they fire >60% of time they're too loose (always confirming).

surprise_vs_anticipation
  - VIX +/-1.5 fires on ~25-30% of bars is ideal.
  - If fire rate > 40%, raise to 2.0.  If < 15%, lower to 1.2.
""")
