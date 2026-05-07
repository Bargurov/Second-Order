"""
stats.bootstrap_ci

Pure deterministic bootstrap mean confidence interval utility for
event-study outputs (abnormal returns, standardized abnormal returns).

Discipline
----------
* Stdlib only (``random``, ``math``). No numpy, no DB, no provider, no LLM.
* Deterministic under a given ``seed`` — same inputs + same seed always
  produce byte-equal results.
* Uses an isolated ``random.Random`` instance; never perturbs the global
  RNG state of the caller.
* Insufficient samples are reported via ``insufficient_data=True`` plus a
  human-readable ``reason``; the function does NOT raise on small inputs,
  because event-study cohorts can legitimately be short.
* Validation errors (bad confidence, negative bootstrap counts, non-numeric
  elements) DO raise — those are programmer mistakes, not data states.

Method
------
Percentile bootstrap of the mean (Efron's basic percentile method):

  1. Drop non-finite values (NaN / inf) from the input.
  2. If the cleaned sample has fewer than ``min_samples`` finite values,
     emit an ``insufficient_data`` payload.
  3. Otherwise resample with replacement ``n_bootstrap`` times, compute
     each resample's mean, sort, and read the ``alpha/2`` and
     ``1 - alpha/2`` percentiles where ``alpha = 1 - confidence``.
"""

from __future__ import annotations

import math
import random
from typing import Any, Iterable

__all__ = (
    "bootstrap_mean_ci",
    "bootstrap_ar_ci",
    "bootstrap_sar_ci",
)


_DEFAULT_CONFIDENCE = 0.95
_DEFAULT_N_BOOTSTRAP = 2000
_DEFAULT_SEED = 0
_DEFAULT_MIN_SAMPLES = 8


def _coerce_finite_floats(samples: Iterable[Any]) -> tuple[list[float], int]:
    """Return ``(finite_values, n_input)``.

    Raises ``TypeError`` for non-iterable input or any element that cannot
    be coerced to a float in a numeric way (str, dict, None, ...). NaN and
    inf are dropped silently — they are valid floats but not usable for a
    mean CI.
    """
    try:
        iterator = iter(samples)
    except TypeError as exc:
        raise TypeError(
            f"samples must be an iterable of numbers, got {type(samples).__name__}"
        ) from exc

    finite: list[float] = []
    n_input = 0
    for x in iterator:
        n_input += 1
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            # Booleans subclass int but conflate logic with magnitude — refuse.
            raise TypeError(
                f"samples must contain only int/float values, got {type(x).__name__}"
            )
        f = float(x)
        if math.isfinite(f):
            finite.append(f)
    return finite, n_input


def _validate_params(
    *,
    confidence: float,
    n_bootstrap: int,
    seed: int,
    min_samples: int,
) -> None:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError(f"seed must be int, got {type(seed).__name__}")
    if not isinstance(n_bootstrap, int) or isinstance(n_bootstrap, bool):
        raise TypeError(
            f"n_bootstrap must be int, got {type(n_bootstrap).__name__}"
        )
    if not isinstance(min_samples, int) or isinstance(min_samples, bool):
        raise TypeError(
            f"min_samples must be int, got {type(min_samples).__name__}"
        )
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise TypeError(
            f"confidence must be a number, got {type(confidence).__name__}"
        )
    if not (0.0 < float(confidence) < 1.0):
        raise ValueError(
            f"confidence must be in the open interval (0, 1); got {confidence}"
        )
    if n_bootstrap < 1:
        raise ValueError(f"n_bootstrap must be >= 1; got {n_bootstrap}")
    if min_samples < 1:
        raise ValueError(f"min_samples must be >= 1; got {min_samples}")


def _empty_payload(
    *,
    n_input: int,
    n: int,
    confidence: float,
    n_bootstrap: int,
    seed: int,
    min_samples: int,
    reason: str,
    kind: str,
) -> dict[str, Any]:
    return {
        "ok": False,
        "n": n,
        "n_input": n_input,
        "mean": None,
        "lower": None,
        "upper": None,
        "confidence": float(confidence),
        "n_bootstrap": int(n_bootstrap),
        "seed": int(seed),
        "min_samples": int(min_samples),
        "insufficient_data": True,
        "reason": reason,
        "kind": kind,
    }


def _percentile_index(p: float, n: int) -> int:
    """Nearest-rank index into a sorted length-``n`` array for percentile ``p``."""
    if n <= 1:
        return 0
    idx = int(round(p * (n - 1)))
    if idx < 0:
        return 0
    if idx > n - 1:
        return n - 1
    return idx


def _bootstrap_core(
    samples: Iterable[Any],
    *,
    confidence: float,
    n_bootstrap: int,
    seed: int,
    min_samples: int,
    kind: str,
) -> dict[str, Any]:
    _validate_params(
        confidence=confidence,
        n_bootstrap=n_bootstrap,
        seed=seed,
        min_samples=min_samples,
    )

    finite, n_input = _coerce_finite_floats(samples)
    n = len(finite)

    if n < min_samples or n < 2:
        if n == 0:
            reason = (
                f"insufficient_data: 0 finite values "
                f"(n_input={n_input}, min_samples={min_samples})"
            )
        elif n < 2:
            reason = (
                f"insufficient_data: n={n} < 2 required for resampling "
                f"(min_samples={min_samples})"
            )
        else:
            reason = (
                f"insufficient_data: n={n} < min_samples={min_samples}"
            )
        return _empty_payload(
            n_input=n_input,
            n=n,
            confidence=confidence,
            n_bootstrap=n_bootstrap,
            seed=seed,
            min_samples=min_samples,
            reason=reason,
            kind=kind,
        )

    sample_mean = sum(finite) / n

    rng = random.Random(seed)
    boot_means: list[float] = []
    randrange = rng.randrange  # local alias hot-path
    for _ in range(n_bootstrap):
        total = 0.0
        for _i in range(n):
            total += finite[randrange(n)]
        boot_means.append(total / n)
    boot_means.sort()

    alpha = 1.0 - float(confidence)
    lo_idx = _percentile_index(alpha / 2.0, n_bootstrap)
    hi_idx = _percentile_index(1.0 - alpha / 2.0, n_bootstrap)

    lower = float(boot_means[lo_idx])
    upper = float(boot_means[hi_idx])

    # Defensive guard: floating-point rounding of identical resamples can
    # invert by a ULP. Clamp to ordered.
    if lower > upper:
        lower, upper = upper, lower

    return {
        "ok": True,
        "n": n,
        "n_input": n_input,
        "mean": float(sample_mean),
        "lower": lower,
        "upper": upper,
        "confidence": float(confidence),
        "n_bootstrap": int(n_bootstrap),
        "seed": int(seed),
        "min_samples": int(min_samples),
        "insufficient_data": False,
        "reason": None,
        "kind": kind,
    }


def bootstrap_mean_ci(
    samples: Iterable[Any],
    *,
    confidence: float = _DEFAULT_CONFIDENCE,
    n_bootstrap: int = _DEFAULT_N_BOOTSTRAP,
    seed: int = _DEFAULT_SEED,
    min_samples: int = _DEFAULT_MIN_SAMPLES,
) -> dict[str, Any]:
    """Percentile-bootstrap mean CI for an arbitrary numeric sample."""
    return _bootstrap_core(
        samples,
        confidence=confidence,
        n_bootstrap=n_bootstrap,
        seed=seed,
        min_samples=min_samples,
        kind="mean",
    )


def bootstrap_ar_ci(
    abnormal_returns: Iterable[Any],
    *,
    confidence: float = _DEFAULT_CONFIDENCE,
    n_bootstrap: int = _DEFAULT_N_BOOTSTRAP,
    seed: int = _DEFAULT_SEED,
    min_samples: int = _DEFAULT_MIN_SAMPLES,
) -> dict[str, Any]:
    """Bootstrap mean CI specifically for abnormal-return series."""
    return _bootstrap_core(
        abnormal_returns,
        confidence=confidence,
        n_bootstrap=n_bootstrap,
        seed=seed,
        min_samples=min_samples,
        kind="ar",
    )


def bootstrap_sar_ci(
    sar_values: Iterable[Any],
    *,
    confidence: float = _DEFAULT_CONFIDENCE,
    n_bootstrap: int = _DEFAULT_N_BOOTSTRAP,
    seed: int = _DEFAULT_SEED,
    min_samples: int = _DEFAULT_MIN_SAMPLES,
) -> dict[str, Any]:
    """Bootstrap mean CI specifically for standardized abnormal returns."""
    return _bootstrap_core(
        sar_values,
        confidence=confidence,
        n_bootstrap=n_bootstrap,
        seed=seed,
        min_samples=min_samples,
        kind="sar",
    )
