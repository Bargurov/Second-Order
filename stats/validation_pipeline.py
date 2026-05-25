"""
stats.validation_pipeline

Composer that takes event-study outputs and emits a stable list of
``stat_validation`` records carrying ``p_value`` and ``fdr_q``.

What this module is
-------------------
A thin, pure-function pipeline that wires together four siblings:

* :mod:`stats.event_study`   — the per-event AR / SAR producer (consumed
                                via its output shape; this module does
                                **not** call ``compute_event_study``
                                itself — callers feed in the outputs).
* :mod:`stats.bootstrap_ci`  — used to compute the percentile bootstrap
                                CI of the cross-sectional mean AR per
                                horizon.
* :mod:`stats.fdr`           — used to apply Benjamini-Hochberg FDR
                                across the per-horizon p-values.
* :mod:`stats.stat_validation` — used to format the final records and
                                  to centralise the significance /
                                  interpretation rules.

What this module is not
-----------------------
* Not a DB writer.  No ``sqlite3``, no archive, no schema mutation.
* Not a provider client.  No ``yfinance``, ``market_data``,
  ``market_check``, LLM, or HTTP.
* Not a UI surface.  No FastAPI, no template, no JSON endpoint.

The pipeline is a pure function: same inputs (and same ``seed``) always
yield byte-equal outputs.  It does not consume the global ``random``
state — :mod:`stats.bootstrap_ci` already isolates its RNG and the
p-value step is closed-form.

Input shape
-----------
``run_validation_pipeline`` accepts two equivalent input forms in the
same list, so a caller doesn't have to flatten ahead of time:

  1. Full ``compute_event_study`` outputs::

         {
           "available": True,
           "horizons": {1: {"abnormal_return": ..., "sar": ..., ...}, ...},
           ...
         }

     Outputs with ``available=False`` are silently skipped (their
     horizon sub-dicts are ``None``-filled by design).

  2. Flat per-horizon rows::

         {"horizon": 5, "abnormal_return": 0.012, "sar": 0.43}

     Extra keys are ignored.  ``abnormal_return`` and ``sar`` may be
     ``None`` or ``NaN`` to signal "missing" — those entries are
     dropped from their per-horizon aggregate.

Per-horizon math
----------------
For every horizon ``h`` that appears at least once in the input:

* ``abnormal_return`` (record) = mean of finite AR observations.
* ``sar``             (record) = mean of finite SAR observations.
* ``ci_low`` / ``ci_high``     = bootstrap percentile CI of the AR
                                  mean via ``bootstrap_ar_ci``; ``None``
                                  when fewer than ``min_samples`` finite
                                  AR observations exist.
* ``p_value``                  = two-sided z-test on the cross-sectional
                                  SAR mean::

                                      z = mean(SAR) / (sd(SAR) / sqrt(n))
                                      p = 2 * (1 - Phi(|z|))

                                  ``None`` when fewer than
                                  ``min_samples`` finite SAR observations
                                  exist or when ``sd(SAR) == 0``.

After every horizon's raw p-value has been computed, the full vector is
fed through :func:`stats.fdr.bh_adjust` and the resulting ``q``-values
are written into the records.  Significance and interpretation are
delegated to :mod:`stats.stat_validation` via
:func:`make_stat_validation_record`, so the rule for "significant" is
identical to every other surface that reads a ``stat_validation`` row.

Output stability
----------------
Records are returned in ascending ``horizon`` order, regardless of input
ordering or duplication.  The output is a fresh ``list[dict]`` — callers
may mutate it without affecting future calls.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable

from stats.bootstrap_ci import bootstrap_ar_ci
from stats.fdr import bh_adjust
from stats.stat_validation import (
    DEFAULT_ALPHA,
    make_stat_validation_record,
)


__all__ = ("run_validation_pipeline",)


_DEFAULT_CONFIDENCE = 0.95
_DEFAULT_N_BOOTSTRAP = 2000
_DEFAULT_SEED = 0
_DEFAULT_MIN_SAMPLES = 8


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _is_finite_number(x: Any) -> bool:
    """True iff ``x`` is a finite real number (rejects bool)."""
    if isinstance(x, bool):
        return False
    if not isinstance(x, (int, float)):
        return False
    return math.isfinite(float(x))


def _coerce_optional_number(value: Any, *, label: str) -> float | None:
    """Allow only None / NaN / finite numbers. Reject str / dict / bool."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{label} must be a number or None; got {type(value).__name__}"
        )
    f = float(value)
    if math.isnan(f):
        return None
    if math.isinf(f):
        # Inf is not a usable observation; drop silently like NaN.
        return None
    return f


def _validate_horizon_value(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"horizon must be a positive int; got {value!r}"
        )
    if value < 1:
        raise ValueError(f"horizon must be >= 1; got {value!r}")
    return int(value)


def _validate_alpha(alpha: Any) -> float:
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
        raise ValueError(
            f"alpha must be a finite number in (0, 1]; got {alpha!r}"
        )
    f = float(alpha)
    if math.isnan(f) or math.isinf(f) or f <= 0.0 or f > 1.0:
        raise ValueError(
            f"alpha must be a finite number in (0, 1]; got {alpha!r}"
        )
    return f


def _validate_confidence(c: Any) -> float:
    # bootstrap_ci will also validate; we mirror the rule here so a bad
    # confidence aborts before we start aggregating.
    if isinstance(c, bool) or not isinstance(c, (int, float)):
        raise ValueError(
            f"confidence must be in (0, 1); got {c!r}"
        )
    f = float(c)
    if not (0.0 < f < 1.0):
        raise ValueError(
            f"confidence must be in (0, 1); got {c!r}"
        )
    return f


def _validate_int_param(value: Any, *, label: str, min_value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, bool):
            raise TypeError(f"{label} must be int; got bool")
        raise TypeError(f"{label} must be int; got {type(value).__name__}")
    if value < min_value:
        raise ValueError(f"{label} must be >= {min_value}; got {value}")
    return value


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _ingest_row(
    row: Any,
    *,
    by_horizon: dict[int, dict[str, list[float]]],
) -> None:
    """Push every (horizon, ar, sar) observation in ``row`` into the bucket."""
    if not isinstance(row, dict):
        raise TypeError(
            f"each input row must be a dict; got {type(row).__name__}"
        )

    # Form 1: full event_study output with a "horizons" sub-dict.
    if isinstance(row.get("horizons"), dict):
        if row.get("available") is False:
            return  # explicitly unavailable — skip silently
        for h_key, fields in row["horizons"].items():
            h = _validate_horizon_value(h_key)
            if not isinstance(fields, dict):
                raise TypeError(
                    f"horizons[{h_key}] must be a dict; got "
                    f"{type(fields).__name__}"
                )
            ar = _coerce_optional_number(
                fields.get("abnormal_return"),
                label=f"horizons[{h}].abnormal_return",
            )
            sar = _coerce_optional_number(
                fields.get("sar"),
                label=f"horizons[{h}].sar",
            )
            car = _coerce_optional_number(
                fields.get("car"),
                label=f"horizons[{h}].car",
            )
            bucket = by_horizon[h]
            bucket["ar"].append(ar)   # type: ignore[arg-type]
            bucket["sar"].append(sar)  # type: ignore[arg-type]
            bucket["car"].append(car)  # type: ignore[arg-type]
        return

    # Form 2: flat per-horizon row.
    if "horizon" not in row:
        raise ValueError(
            "input row must carry a 'horizon' key (or a 'horizons' dict)"
        )
    h = _validate_horizon_value(row["horizon"])
    ar  = _coerce_optional_number(
        row.get("abnormal_return"), label="abnormal_return",
    )
    sar = _coerce_optional_number(row.get("sar"), label="sar")
    car = _coerce_optional_number(row.get("car"), label="car")
    bucket = by_horizon[h]
    bucket["ar"].append(ar)   # type: ignore[arg-type]
    bucket["sar"].append(sar)  # type: ignore[arg-type]
    bucket["car"].append(car)  # type: ignore[arg-type]


def _mean_of_finite(values: list[Any]) -> float | None:
    finite = [float(v) for v in values if _is_finite_number(v)]
    if not finite:
        return None
    return sum(finite) / len(finite)


def _two_sided_z_p_value(
    sar_values: list[Any],
    *,
    min_samples: int,
) -> float | None:
    """Two-sided one-sample z-test on the cross-sectional SAR mean.

    Under H0: mean(SAR) = 0. With a sample of finite SARs of size n,
    using the sample standard deviation (ddof=1) the test statistic is::

        z = mean(SAR) / (sd(SAR) / sqrt(n))

    and the two-sided p-value is ``2 * (1 - Phi(|z|))``. SAR is already
    standardized (per :mod:`stats.event_study`) so a normal-approximation
    z-test is the standard event-study cross-sectional surface.

    Returns ``None`` when ``n < min_samples``, ``n < 2``, or
    ``sd(SAR) == 0``.
    """
    finite = [float(v) for v in sar_values if _is_finite_number(v)]
    n = len(finite)
    if n < min_samples or n < 2:
        return None
    mean_sar = sum(finite) / n
    var = sum((x - mean_sar) ** 2 for x in finite) / (n - 1)
    if var <= 0.0:
        return None
    se = math.sqrt(var / n)
    if se == 0.0:
        return None
    z = mean_sar / se
    cdf = 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0)))
    p = 2.0 * (1.0 - cdf)
    if p < 0.0:
        return 0.0
    if p > 1.0:
        return 1.0
    return p


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_validation_pipeline(
    event_study_inputs: Iterable[Any],
    *,
    alpha: float = DEFAULT_ALPHA,
    confidence: float = _DEFAULT_CONFIDENCE,
    n_bootstrap: int = _DEFAULT_N_BOOTSTRAP,
    seed: int = _DEFAULT_SEED,
    min_samples: int = _DEFAULT_MIN_SAMPLES,
) -> list[dict[str, Any]]:
    """Compose event-study, bootstrap CI, p-values, and FDR into records.

    See module docstring for the full contract.

    Parameters
    ----------
    event_study_inputs
        Iterable of dicts. Each may be a full ``compute_event_study``
        output (with a ``horizons`` sub-dict) or a flat per-horizon row
        (``{horizon, abnormal_return, sar}``). Mixing forms is fine.
    alpha
        Discovery threshold for ``statistically_significant``.
        Forwarded to :func:`make_stat_validation_record` and to
        :func:`bh_adjust`.
    confidence
        Confidence level for the bootstrap CI on the AR mean.
    n_bootstrap, seed, min_samples
        Forwarded to :func:`bootstrap_ar_ci`. ``min_samples`` also gates
        the per-horizon p-value: a horizon with fewer finite SARs than
        ``min_samples`` gets ``p_value = None``.

    Returns
    -------
    list of dict
        ``stat_validation`` records, one per unique horizon present in
        the input, sorted ascending by horizon. Always a fresh list.
    """
    # Validate scalar params first so a bad call aborts before iteration.
    alpha_f      = _validate_alpha(alpha)
    confidence_f = _validate_confidence(confidence)
    n_boot       = _validate_int_param(
        n_bootstrap, label="n_bootstrap", min_value=1,
    )
    seed_i       = _validate_int_param(seed, label="seed", min_value=-(2**31))
    min_samp     = _validate_int_param(
        min_samples, label="min_samples", min_value=1,
    )

    # Materialise input. Reject non-iterable up front.
    try:
        rows = list(event_study_inputs)
    except TypeError as exc:
        raise TypeError(
            f"event_study_inputs must be iterable; got "
            f"{type(event_study_inputs).__name__}"
        ) from exc

    by_horizon: dict[int, dict[str, list[float]]] = defaultdict(
        lambda: {"ar": [], "sar": [], "car": []},
    )
    for row in rows:
        _ingest_row(row, by_horizon=by_horizon)

    if not by_horizon:
        return []

    horizons_sorted = sorted(by_horizon.keys())

    # Per-horizon: aggregate, CI, raw p-value. Defer FDR + record build
    # until the full p-value vector is known.
    pending: list[dict[str, Any]] = []
    raw_p_values: list[float | None] = []
    for h in horizons_sorted:
        ar_obs  = by_horizon[h]["ar"]
        sar_obs = by_horizon[h]["sar"]

        car_obs = by_horizon[h]["car"]

        mean_ar  = _mean_of_finite(ar_obs)
        mean_sar = _mean_of_finite(sar_obs)
        mean_car = _mean_of_finite(car_obs)

        # Sort the AR sample before bootstrapping so the seeded percentile
        # bootstrap is order-invariant w.r.t. the input row order — same
        # multiset of observations, same CI. The mean is order-invariant
        # by definition; sorting just pins the resample sequence.
        finite_ar_sorted = sorted(float(v) for v in ar_obs if _is_finite_number(v))
        ci_dict = bootstrap_ar_ci(
            finite_ar_sorted,
            confidence=confidence_f,
            n_bootstrap=n_boot,
            seed=seed_i,
            min_samples=min_samp,
        )
        if ci_dict["ok"]:
            ci_low  = ci_dict["lower"]
            ci_high = ci_dict["upper"]
        else:
            ci_low = None
            ci_high = None

        p_value = _two_sided_z_p_value(sar_obs, min_samples=min_samp)

        pending.append({
            "horizon":         h,
            "abnormal_return": mean_ar,
            "sar":             mean_sar,
            "car":             mean_car,
            "ci_low":          ci_low,
            "ci_high":         ci_high,
        })
        raw_p_values.append(p_value)

    # FDR adjustment across horizons. bh_adjust treats None as invalid
    # and preserves the position with adjusted=None — exactly what the
    # record needs (insufficient horizons stay flagged as such).
    adjusted = bh_adjust(raw_p_values, alpha=alpha_f)["adjusted"]

    # Finalise records via stat_validation so significance and
    # interpretation use the canonical rule.
    out: list[dict[str, Any]] = []
    for slot, raw_p, q in zip(pending, raw_p_values, adjusted):
        record = make_stat_validation_record(
            horizon=slot["horizon"],
            abnormal_return=slot["abnormal_return"],
            sar=slot["sar"],
            car=slot["car"],
            ci_low=slot["ci_low"],
            ci_high=slot["ci_high"],
            p_value=raw_p,
            fdr_q=q,
            alpha=alpha_f,
        )
        out.append(record)
    return out
