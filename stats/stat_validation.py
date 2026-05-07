"""Statistical validation record schema.

Composes the three concepts a research-quality event-study row carries
— the event-study point estimate, the confidence interval, and the
FDR-adjusted q-value — into a stable nine-field dict payload an
operator or downstream renderer can rely on.

Pure schema / types module
--------------------------
* No DB seam.  No ``sqlite3`` import.
* No UI seam.  No FastAPI app, no ``routes.*`` import.
* No provider seam.  No ``yfinance``, ``market_data``, ``market_check``,
  or LLM import.
* No archive mutation.  The module never writes anything anywhere.

The companion :mod:`stats.fdr` module owns the Benjamini-Hochberg
adjustment itself; this module only stores the resulting ``fdr_q``
and decides significance against a configurable alpha.  Significance
follows the BH discovery rule used in ``stats/fdr.py``
(``q <= alpha``) so a row flagged as a BH discovery is never
relabeled "not significant" by this surface.

Canonical fields
----------------
The record exposes nine keys in a fixed order so a downstream renderer
can iterate :data:`STAT_VALIDATION_FIELDS` for stable layout::

    horizon                    int   >= 1, e.g. 1, 5, 20
    abnormal_return            float | None
    sar                        float | None  (standardized AR)
    ci_low                     float | None  (lower CI bound)
    ci_high                    float | None  (upper CI bound)
    p_value                    float | None  (raw p, in [0, 1])
    fdr_q                      float | None  (BH-adjusted q, in [0, 1])
    statistically_significant  bool
    interpretation             str   (one of :data:`INTERPRETATIONS`)

Interpretation vocabulary
-------------------------
:data:`INTERPRETATIONS` is the closed set of labels the
``interpretation`` field can carry.  Adding a label is a contract
change.

NaN normalization
-----------------
Optional numeric inputs accept ``None`` or ``NaN`` to signal "missing".
Both are normalized to ``None`` inside the record so the payload
round-trips through ``json.dumps(..., allow_nan=False)`` without
raising.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Optional


__all__ = [
    "STAT_VALIDATION_FIELDS",
    "INTERPRETATIONS",
    "INTERPRETATION_SIGNIFICANT_POSITIVE",
    "INTERPRETATION_SIGNIFICANT_NEGATIVE",
    "INTERPRETATION_NOT_SIGNIFICANT",
    "INTERPRETATION_INSUFFICIENT_DATA",
    "DEFAULT_ALPHA",
    "make_event_study_fields",
    "make_ci_fields",
    "make_fdr_fields",
    "is_statistically_significant",
    "derive_interpretation",
    "make_stat_validation_record",
    "compose_validation_records",
]


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------


STAT_VALIDATION_FIELDS: tuple[str, ...] = (
    "horizon",
    "abnormal_return",
    "sar",
    "ci_low",
    "ci_high",
    "p_value",
    "fdr_q",
    "statistically_significant",
    "interpretation",
)


INTERPRETATION_SIGNIFICANT_POSITIVE = "significant_positive"
INTERPRETATION_SIGNIFICANT_NEGATIVE = "significant_negative"
INTERPRETATION_NOT_SIGNIFICANT      = "not_significant"
INTERPRETATION_INSUFFICIENT_DATA    = "insufficient_data"


INTERPRETATIONS: tuple[str, ...] = (
    INTERPRETATION_SIGNIFICANT_POSITIVE,
    INTERPRETATION_SIGNIFICANT_NEGATIVE,
    INTERPRETATION_NOT_SIGNIFICANT,
    INTERPRETATION_INSUFFICIENT_DATA,
)


DEFAULT_ALPHA: float = 0.05


# ---------------------------------------------------------------------------
# Validation primitives
# ---------------------------------------------------------------------------


def _coerce_optional_number(value: Any, label: str) -> Optional[float]:
    """Normalize a numeric input to ``Optional[float]``.

    ``None`` and ``NaN`` both collapse to ``None``.  ``bool`` is
    rejected (Python ``bool`` is a subclass of ``int`` but a boolean
    is never a meaningful statistic).  Inf is also rejected — a
    finite real or "missing" are the only well-formed cases.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(
            f"{label} must be a finite real or None; got {value!r}"
        )
    if not isinstance(value, (int, float)):
        raise ValueError(
            f"{label} must be a finite real or None; got {value!r}"
        )
    f = float(value)
    if math.isnan(f):
        return None
    if math.isinf(f):
        raise ValueError(
            f"{label} must be finite or None; got {value!r}"
        )
    return f


def _validate_horizon(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"horizon must be a positive int; got {value!r}"
        )
    if value < 1:
        raise ValueError(
            f"horizon must be >= 1; got {value!r}"
        )
    return value


def _validate_unit_interval(
    value: Optional[float], label: str,
) -> Optional[float]:
    if value is None:
        return None
    if not 0.0 <= value <= 1.0:
        raise ValueError(
            f"{label} must be in [0, 1]; got {value!r}"
        )
    return value


def _validate_alpha(alpha: Any) -> float:
    """Coerce alpha to float in ``(0, 1]`` matching ``stats.fdr``."""
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


# ---------------------------------------------------------------------------
# Sub-schemas — caller can build a partial slice when only one concept
# is available, then merge externally.  The composer below uses these
# under the hood so the validation rules stay in one place.
# ---------------------------------------------------------------------------


def make_event_study_fields(
    *,
    horizon: int,
    abnormal_return: Any,
    sar: Any,
) -> dict[str, Any]:
    """Return the event-study slice ``{horizon, abnormal_return, sar}``.

    Raises ``ValueError`` on a non-positive / non-int horizon or on a
    non-numeric abnormal_return / sar.  ``None`` and ``NaN`` are both
    accepted for the two numeric fields and normalize to ``None``.
    """
    return {
        "horizon":         _validate_horizon(horizon),
        "abnormal_return": _coerce_optional_number(
            abnormal_return, "abnormal_return",
        ),
        "sar":             _coerce_optional_number(sar, "sar"),
    }


def make_ci_fields(
    *,
    ci_low:  Any,
    ci_high: Any,
) -> dict[str, Any]:
    """Return the CI slice ``{ci_low, ci_high}``.

    ``None`` and ``NaN`` collapse to ``None`` on either bound.  When
    both bounds are present, ``ci_low`` must not exceed ``ci_high``
    (equal bounds are accepted — a degenerate but well-formed point
    estimate).
    """
    low  = _coerce_optional_number(ci_low,  "ci_low")
    high = _coerce_optional_number(ci_high, "ci_high")
    if low is not None and high is not None and low > high:
        raise ValueError(
            f"ci_low must not exceed ci_high; got {low!r} > {high!r}"
        )
    return {"ci_low": low, "ci_high": high}


def make_fdr_fields(
    *,
    p_value: Any,
    fdr_q:   Any,
) -> dict[str, Any]:
    """Return the FDR slice ``{p_value, fdr_q}``.

    Both fields must lie in ``[0, 1]`` when provided.  ``None`` and
    ``NaN`` collapse to ``None``.
    """
    p = _coerce_optional_number(p_value, "p_value")
    q = _coerce_optional_number(fdr_q,   "fdr_q")
    return {
        "p_value": _validate_unit_interval(p, "p_value"),
        "fdr_q":   _validate_unit_interval(q, "fdr_q"),
    }


# ---------------------------------------------------------------------------
# Significance and interpretation
# ---------------------------------------------------------------------------


def is_statistically_significant(
    fdr_q: Any,
    *,
    alpha: float = DEFAULT_ALPHA,
) -> bool:
    """True iff ``fdr_q`` is a finite real and ``fdr_q <= alpha``.

    ``None`` and ``NaN`` both return ``False``.  ``alpha`` must lie in
    ``(0, 1]`` (matching :mod:`stats.fdr`); other values raise.
    """
    alpha_f = _validate_alpha(alpha)
    q = _coerce_optional_number(fdr_q, "fdr_q")
    if q is None:
        return False
    return q <= alpha_f


def derive_interpretation(
    *,
    abnormal_return: Any,
    statistically_significant: bool,
) -> str:
    """Pick an :data:`INTERPRETATIONS` label.

    * ``insufficient_data`` if ``abnormal_return`` is ``None`` or
      ``NaN`` — even when the caller force-passes
      ``statistically_significant=True``, we cannot label direction
      without an AR.
    * ``significant_positive`` if significant and ``AR > 0``.
    * ``significant_negative`` if significant and ``AR < 0``.
    * ``not_significant`` otherwise.  ``AR == 0`` with significance
      collapses to ``not_significant`` because there is no direction
      to report.
    """
    ar = _coerce_optional_number(abnormal_return, "abnormal_return")
    if ar is None:
        return INTERPRETATION_INSUFFICIENT_DATA
    if statistically_significant and ar > 0:
        return INTERPRETATION_SIGNIFICANT_POSITIVE
    if statistically_significant and ar < 0:
        return INTERPRETATION_SIGNIFICANT_NEGATIVE
    return INTERPRETATION_NOT_SIGNIFICANT


# ---------------------------------------------------------------------------
# Composed record
# ---------------------------------------------------------------------------


def make_stat_validation_record(
    *,
    horizon:         int,
    abnormal_return: Any,
    sar:             Any,
    ci_low:          Any,
    ci_high:         Any,
    p_value:         Any,
    fdr_q:           Any,
    alpha:           float = DEFAULT_ALPHA,
) -> dict[str, Any]:
    """Compose a full nine-field validation record.

    Validates each input, derives ``statistically_significant`` from
    ``fdr_q`` vs ``alpha``, and labels ``interpretation`` from the
    sign of ``abnormal_return`` plus the significance bool.

    The returned dict's keys are inserted in
    :data:`STAT_VALIDATION_FIELDS` order — Python 3.7+ preserves
    insertion order, so iterating ``record.items()`` yields the
    canonical order.  All optional numeric fields are normalized to
    ``Optional[float]`` (NaN → None) so the record is JSON-serializable
    with ``allow_nan=False``.
    """
    # Validate alpha early so a bad alpha aborts before we build a
    # half-formed record.
    alpha_f = _validate_alpha(alpha)

    es  = make_event_study_fields(
        horizon=horizon,
        abnormal_return=abnormal_return,
        sar=sar,
    )
    ci  = make_ci_fields(ci_low=ci_low, ci_high=ci_high)
    fdr = make_fdr_fields(p_value=p_value, fdr_q=fdr_q)

    significant = is_statistically_significant(
        fdr["fdr_q"], alpha=alpha_f,
    )
    interpretation = derive_interpretation(
        abnormal_return=es["abnormal_return"],
        statistically_significant=significant,
    )

    # Insert in canonical order so iteration matches
    # STAT_VALIDATION_FIELDS row-for-row.
    record: dict[str, Any] = {}
    record["horizon"]                   = es["horizon"]
    record["abnormal_return"]           = es["abnormal_return"]
    record["sar"]                       = es["sar"]
    record["ci_low"]                    = ci["ci_low"]
    record["ci_high"]                   = ci["ci_high"]
    record["p_value"]                   = fdr["p_value"]
    record["fdr_q"]                     = fdr["fdr_q"]
    record["statistically_significant"] = significant
    record["interpretation"]            = interpretation
    return record


def compose_validation_records(
    inputs: Iterable[dict[str, Any]],
    *,
    alpha: float = DEFAULT_ALPHA,
) -> list[dict[str, Any]]:
    """Build a list of records from a sequence of input dicts.

    Each input dict is forwarded as keyword arguments to
    :func:`make_stat_validation_record`.  Order is preserved so a
    caller that constructed the inputs in horizon order reads them
    back in the same order.

    A single bad row aborts the whole composition with the underlying
    ``ValueError`` — partial composition would silently drop a row,
    which is a worse contract than failing loudly.
    """
    return [
        make_stat_validation_record(alpha=alpha, **row)
        for row in inputs
    ]
