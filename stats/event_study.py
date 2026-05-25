"""Event-study abnormal-return engine.

Pure numpy compute path.  Given two aligned price arrays (asset +
benchmark), an ``event_index``, and one or more horizons, returns
five numbers per horizon:

  * ``raw_return``       — buy-and-hold return of the asset over the
                           horizon: ``(P[t+h] - P[t]) / P[t]``.
  * ``benchmark_return`` — buy-and-hold return of the benchmark over
                           the same horizon.
  * ``abnormal_return``  — ``raw_return - benchmark_return``
                           (BHAR-style market-adjusted return).
  * ``sar``              — ``abnormal_return / (sigma_ar_daily *
                           sqrt(h))`` where ``sigma_ar_daily`` is the
                           sample standard deviation (``ddof=1``) of
                           the daily AR series over the estimation
                           window (``event_index - estimation_window
                           .. event_index``).
  * ``car``              — cumulative abnormal return: the sum of the
                           daily abnormal returns from ``event_index+1``
                           through ``event_index+h``.  At ``h=1`` this
                           equals the BHAR ``abnormal_return`` exactly;
                           at larger horizons the two diverge because
                           BHAR compounds while CAR sums.

Convention notes
----------------
The BHAR ``abnormal_return`` and the ``sigma_ar_daily * sqrt(h)`` SAR
denominator come from two different return conventions (compounded
vs additive).  At horizons ≤20 days the theoretical mismatch is
small; the engine intentionally surfaces the buy-and-hold AR (what
an investor would observe) and uses the additive-AR sigma scaling
(what is computable cheaply from a daily AR series).  The ``car``
field provides the classical sum-of-daily-AR measure alongside
the BHAR ``abnormal_return`` so callers can compare both without
re-deriving the daily AR series.

Read-only / no I/O
------------------
No DB access, no provider calls, no LLM, no FastAPI surface.  The
module imports ``math`` and ``numpy`` only.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np


_DEFAULT_HORIZONS: tuple[int, ...] = (1, 5, 20)
_DEFAULT_ESTIMATION_WINDOW: int = 60


def _to_array(values: Any, *, name: str) -> np.ndarray:
    """Coerce ``values`` to a 1-D float numpy array.

    Accepts list / tuple / ndarray / pandas Series — anything
    ``np.asarray`` can convert.  Validates positivity + finiteness
    here so every code path downstream can assume clean data.
    """
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        raise ValueError(
            f"{name} must be 1-D; got shape {arr.shape}",
        )
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} contains NaN or inf")
    if np.any(arr <= 0):
        raise ValueError(f"{name} contains non-positive values")
    return arr


def _empty_horizons(horizons: Sequence[int]) -> dict[int, dict]:
    return {
        int(h): {
            "raw_return":       None,
            "benchmark_return": None,
            "abnormal_return":  None,
            "sar":              None,
            "car":              None,
        }
        for h in horizons
    }


def _validate_horizons(horizons: Sequence[int]) -> tuple[int, ...]:
    out: list[int] = []
    for h in horizons:
        h_int = int(h)
        if h_int <= 0:
            raise ValueError(
                f"horizons must be positive integers; got {h!r}",
            )
        out.append(h_int)
    return tuple(out)


def compute_event_study(
    *,
    asset_prices: Any,
    benchmark_prices: Any,
    event_index: int,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    estimation_window: int = _DEFAULT_ESTIMATION_WINDOW,
) -> dict:
    """Compute raw, benchmark, abnormal, and standardized abnormal
    returns at each requested horizon.

    Parameters
    ----------
    asset_prices : sequence of floats
        Aligned asset close prices.  Must be all positive and finite.
    benchmark_prices : sequence of floats
        Aligned benchmark close prices.  Same length as
        ``asset_prices``.
    event_index : int
        Index in the price arrays corresponding to ``t=0`` (the event
        close).  Returns are computed forward from this index.
    horizons : sequence of int, default ``(1, 5, 20)``
        Forward horizons (in trading days) to compute.
    estimation_window : int, default ``60``
        Number of pre-event daily returns used to estimate
        ``sigma_ar_daily``.  Requires
        ``event_index >= estimation_window``.

    Returns
    -------
    dict
        ``{available, horizons, estimation_window_used, sigma_ar_daily,
        warnings}``.  The ``horizons`` sub-dict always contains every
        requested horizon as an integer key, even when one or more
        fields could not be computed (those fields are ``None``).

    Raises
    ------
    ValueError
        On caller bugs: mismatched array lengths, non-positive prices,
        NaN / inf prices, ``event_index`` out of range, non-positive
        horizons.  Conditions that arise from data-availability gaps
        (insufficient estimation window, horizon overflow,
        ``sigma=0``) are surfaced via ``warnings`` rather than raised.
    """
    horizons = _validate_horizons(horizons)
    asset = _to_array(asset_prices,    name="asset_prices")
    bench = _to_array(benchmark_prices, name="benchmark_prices")
    if asset.shape != bench.shape:
        raise ValueError(
            f"asset_prices and benchmark_prices must have matching "
            f"length; got {asset.size} vs {bench.size}",
        )
    n = asset.size
    if not (0 <= event_index < n):
        raise ValueError(
            f"event_index {event_index} out of range for length-{n} "
            f"price array",
        )
    if int(estimation_window) <= 0:
        raise ValueError(
            f"estimation_window must be positive; got {estimation_window!r}",
        )

    warnings: list[str] = []

    # Estimation window check ------------------------------------------------
    if event_index < estimation_window:
        warnings.append(
            f"insufficient estimation window: event_index={event_index} "
            f"< requested estimation_window={estimation_window}; cannot "
            f"compute sigma_ar_daily.  No horizons computed.",
        )
        return {
            "available":              False,
            "horizons":               _empty_horizons(horizons),
            "estimation_window_used": 0,
            "sigma_ar_daily":         None,
            "warnings":               warnings,
        }

    # Daily AR series over the estimation window -----------------------------
    est_start = event_index - estimation_window
    asset_est = asset[est_start: event_index + 1]
    bench_est = bench[est_start: event_index + 1]
    asset_ret = (asset_est[1:] / asset_est[:-1]) - 1.0
    bench_ret = (bench_est[1:] / bench_est[:-1]) - 1.0
    daily_ar  = asset_ret - bench_ret
    estimation_window_used = int(daily_ar.size)

    # ddof=1 → sample stddev.  np.std on a length-1 array with ddof=1
    # returns NaN with a RuntimeWarning; we treat NaN the same as 0.0
    # via the ``not isfinite or == 0`` predicate below, but suppress
    # the warning so unrelated callers do not see noise.
    if estimation_window_used >= 2:
        sigma_ar_daily = float(np.std(daily_ar, ddof=1))
    else:
        sigma_ar_daily = float("nan")

    sigma_ok = math.isfinite(sigma_ar_daily) and sigma_ar_daily > 0.0
    if not sigma_ok:
        if not math.isfinite(sigma_ar_daily):
            warnings.append(
                "sigma_ar_daily is NaN (estimation window too short for "
                "ddof=1 sample std); SAR is None for every horizon.",
            )
            sigma_ar_daily_value: float | None = None
        else:
            warnings.append(
                "sigma_ar_daily is 0 (asset and benchmark daily returns "
                "agreed exactly through the estimation window); SAR is "
                "None for every horizon.",
            )
            sigma_ar_daily_value = 0.0
    else:
        sigma_ar_daily_value = sigma_ar_daily

    # Event-window daily ARs for CAR computation -----------------------------
    if horizons:
        max_forward = max(horizons)
        max_forward_idx = min(event_index + max_forward, n - 1)
        if max_forward_idx > event_index:
            asset_event = asset[event_index: max_forward_idx + 1]
            bench_event = bench[event_index: max_forward_idx + 1]
            asset_event_ret = (asset_event[1:] / asset_event[:-1]) - 1.0
            bench_event_ret = (bench_event[1:] / bench_event[:-1]) - 1.0
            daily_ar_event = asset_event_ret - bench_event_ret
            cum_ar = np.cumsum(daily_ar_event)
        else:
            cum_ar = np.array([], dtype=float)
    else:
        cum_ar = np.array([], dtype=float)

    # Per-horizon AR + SAR + CAR --------------------------------------------
    event_close_asset = float(asset[event_index])
    event_close_bench = float(bench[event_index])
    horizon_results: dict[int, dict] = {}
    for h in horizons:
        forward_idx = event_index + h
        if forward_idx >= n:
            warnings.append(
                f"horizon h={h} extends beyond price array "
                f"(event_index+h={forward_idx} >= len={n}); horizon "
                f"fields are None.",
            )
            horizon_results[h] = {
                "raw_return":       None,
                "benchmark_return": None,
                "abnormal_return":  None,
                "sar":              None,
                "car":              None,
            }
            continue

        raw       = float(asset[forward_idx]) / event_close_asset - 1.0
        bench_ret = float(bench[forward_idx]) / event_close_bench - 1.0
        ar        = raw - bench_ret
        if sigma_ok:
            sar: float | None = ar / (sigma_ar_daily * math.sqrt(h))
        else:
            sar = None
        car: float | None = float(cum_ar[h - 1]) if h <= cum_ar.size else None
        horizon_results[h] = {
            "raw_return":       raw,
            "benchmark_return": bench_ret,
            "abnormal_return":  ar,
            "sar":              sar,
            "car":              car,
        }

    return {
        "available":              True,
        "horizons":               horizon_results,
        "estimation_window_used": estimation_window_used,
        "sigma_ar_daily":         sigma_ar_daily_value,
        "warnings":               warnings,
    }


__all__ = ("compute_event_study",)
