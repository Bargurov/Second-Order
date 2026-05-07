"""Normal-distribution p-values for SAR / abnormal-return testing.

Pure stdlib (``math`` only).  No DB seam, no provider, no LLM, no
filesystem.  Mirrors :mod:`stats.fdr` / :mod:`stats.event_study` in
keeping the surface tiny and dependency-free.

Single entry point
------------------

:func:`p_value_from_sar(sar, alternative="two-sided")`

Treats ``sar`` as a draw from a standard normal under the null and
returns the corresponding p-value.

Alternatives
------------

  * ``"two-sided"`` (default) — ``P(|Z| >= |sar|) = erfc(|sar|/√2)``.
  * ``"greater"``  — ``P(Z >= sar) = 0.5 * erfc(sar/√2)``.
  * ``"less"``     — ``P(Z <= sar) = 0.5 * erfc(-sar/√2)``.

Strings are matched literally.  Common variants (``"Two-sided"``,
``"GREATER"``, R's ``"two.sided"``) raise :class:`ValueError` so caller
bugs surface immediately rather than silently flipping to a different
test.

Missing input
-------------

``None`` and ``NaN`` map to ``None`` — there is no defensible default
p-value for a missing test statistic, and propagating ``None``
matches the convention used by :mod:`stats.event_study` for
unavailable horizon fields.

``±inf`` flows through ``math.erfc`` cleanly:

  * ``erfc(+inf) = 0`` → infinite-magnitude evidence against the null.
  * ``erfc(-inf) = 2`` → impossible-by-direction; the one-sided
    branches resolve to ``0`` or ``1`` accordingly.

The alternative string is validated **before** the missing-input
check, so ``p_value_from_sar(None, alternative="bogus")`` raises
:class:`ValueError` rather than silently returning ``None``.
"""
from __future__ import annotations

import math
from typing import Any


_VALID_ALTERNATIVES: frozenset[str] = frozenset(
    {"two-sided", "greater", "less"},
)
_SQRT2: float = math.sqrt(2.0)


def _is_missing(sar: Any) -> bool:
    if sar is None:
        return True
    try:
        x = float(sar)
    except (TypeError, ValueError):
        return True
    return math.isnan(x)


def p_value_from_sar(
    sar: Any,
    alternative: str = "two-sided",
) -> float | None:
    """Normal p-value for ``sar`` under the chosen alternative.

    Parameters
    ----------
    sar : float or None
        Test statistic — typically a standardized abnormal return from
        :func:`stats.event_study.compute_event_study`.  ``None`` /
        ``NaN`` propagate as ``None``.  ``±inf`` is allowed.
    alternative : {"two-sided", "greater", "less"}, default "two-sided"
        Hypothesis direction.  Matched case-sensitively against the
        three literal strings — variants raise :class:`ValueError`.

    Returns
    -------
    float | None
        A p-value in ``[0.0, 1.0]``, or ``None`` when ``sar`` is
        missing.

    Raises
    ------
    ValueError
        If ``alternative`` is not one of the three supported strings.
    """
    if not isinstance(alternative, str):
        raise ValueError(
            f"alternative must be a string; got {type(alternative).__name__}",
        )
    if alternative not in _VALID_ALTERNATIVES:
        raise ValueError(
            f"alternative must be one of "
            f"{sorted(_VALID_ALTERNATIVES)!r}; got {alternative!r}",
        )

    if _is_missing(sar):
        return None

    z = float(sar)

    if alternative == "two-sided":
        return math.erfc(abs(z) / _SQRT2)
    if alternative == "greater":
        return 0.5 * math.erfc(z / _SQRT2)
    # alternative == "less"
    return 0.5 * math.erfc(-z / _SQRT2)


__all__ = ("p_value_from_sar",)
