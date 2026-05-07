"""Benjamini-Hochberg false-discovery-rate correction.

Pure-Python, deterministic, dependency-free.  No filesystem, no
network, no DB seam, no provider, no LLM, no project imports — the
module stands alone and can be unit-tested in isolation.

Single entry point
------------------

:func:`bh_adjust(p_values, *, alpha=0.05)`

Returns a dict::

    {
      "adjusted":        list[float | None],  # same length as input
      "discoveries":     list[bool],          # same length as input
      "num_discoveries": int,                 # sum of ``discoveries``
      "m":               int,                 # count of valid p-values
      "alpha":           float,               # echo of the input
    }

Algorithm
---------

For every valid p-value at sorted rank ``k`` (1-indexed, ``m`` valid
total)::

    raw_q_(k) = (m / k) * p_(k)

The adjusted p-value is the running minimum of ``raw_q`` walked from
the largest rank down to the smallest, clamped to ``[0, 1]``::

    q_(k) = min(1, min over j >= k of raw_q_(j))

This matches R's ``p.adjust(p, method = "BH")`` and is the standard
Benjamini-Hochberg adjusted p-value.  The running-min step enforces
monotonicity in sorted-rank order so ties never get inverted
adjustments.

Invalid p-values
----------------

Any input that is not a finite real in ``[0, 1]`` is treated as
**invalid**.  This includes:

  * ``None``
  * ``True`` / ``False``  (Python ``bool`` is a subclass of ``int``,
    but a boolean is never a meaningful p-value)
  * Non-numeric types (``str``, ``bytes``, ``dict``, ``list``, ...)
  * ``float('nan')`` and ``±float('inf')``
  * Values strictly less than ``0`` or strictly greater than ``1``

Invalid entries:

  * carry ``adjusted = None`` and ``discoveries = False`` at their
    original index;
  * do **not** contribute to ``m``;
  * do **not** shift the rank of any valid p-value.

Discovery rule
--------------

A discovery is declared at index ``i`` iff the adjusted p-value at
``i`` is non-``None`` and ``<= alpha``.  This is the conventional
Benjamini-Hochberg threshold and matches the original step-up
procedure: rejecting at adjusted ``<= alpha`` selects exactly the
same hypotheses as the original BH rule that finds the largest
``k`` with ``p_(k) <= (k/m) * alpha``.

Input invariants
----------------

* ``p_values`` is a finite-length iterable.  It is consumed once
  via ``list(p_values)`` and never mutated.  Any iterable that can
  be materialised is acceptable.
* ``alpha`` must be a finite real in ``(0, 1]``.  Out-of-range or
  non-numeric ``alpha`` raises ``ValueError``; ``bool`` is also
  rejected.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

__all__ = ["bh_adjust"]


_DEFAULT_ALPHA: float = 0.05


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _is_valid_pvalue(x: Any) -> bool:
    """Return True iff ``x`` is a finite real in ``[0, 1]`` and not ``bool``.

    ``bool`` is a subclass of ``int`` in Python, so ``isinstance(True,
    int)`` is True; we reject it explicitly because ``True``/``False``
    is never a meaningful p-value and accepting it silently would let
    type errors flow through the adjustment unchanged.
    """
    if isinstance(x, bool):
        return False
    if not isinstance(x, (int, float)):
        return False
    xf = float(x)
    if math.isnan(xf) or math.isinf(xf):
        return False
    return 0.0 <= xf <= 1.0


def _validate_alpha(alpha: Any) -> float:
    """Coerce ``alpha`` to a float in ``(0, 1]`` or raise ``ValueError``.

    Mirrors the p-value validator's strictness — a ``bool`` is
    explicitly rejected so an accidental ``alpha=True`` doesn't
    silently coerce to ``1.0``.
    """
    if isinstance(alpha, bool):
        raise ValueError(
            f"alpha must be a finite number in (0, 1]; got {alpha!r}"
        )
    if not isinstance(alpha, (int, float)):
        raise ValueError(
            f"alpha must be a finite number in (0, 1]; got {alpha!r}"
        )
    af = float(alpha)
    if math.isnan(af) or math.isinf(af) or af <= 0.0 or af > 1.0:
        raise ValueError(
            f"alpha must be a finite number in (0, 1]; got {alpha!r}"
        )
    return af


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def bh_adjust(
    p_values: Iterable[Any],
    *,
    alpha: float = _DEFAULT_ALPHA,
) -> dict[str, Any]:
    """Compute Benjamini-Hochberg adjusted p-values + discovery flags.

    See module docstring for the full contract.  The returned dict's
    list fields have the same length as ``p_values`` and preserve the
    input order; entries at invalid input positions are ``None`` /
    ``False``.

    Raises
    ------
    ValueError
        If ``alpha`` is not a finite real in ``(0, 1]``.
    """
    alpha_f = _validate_alpha(alpha)

    pvs = list(p_values)
    n = len(pvs)
    adjusted: list[float | None] = [None] * n
    discoveries: list[bool] = [False] * n

    # Index every entry that passes the validator.  Order-preserving
    # so the tie-break below is deterministic.
    valid_indices: list[int] = [
        i for i, p in enumerate(pvs) if _is_valid_pvalue(p)
    ]
    m = len(valid_indices)

    if m == 0:
        return {
            "adjusted":        adjusted,
            "discoveries":     discoveries,
            "num_discoveries": 0,
            "m":               m,
            "alpha":           alpha_f,
        }

    # Sort valid entries ascending by p-value; tie-break by original
    # index for deterministic ordering.  The BH math is tie-invariant
    # via the cumulative min, so the tie-break only pins the sort —
    # equal p-values still receive equal adjusted values.
    sorted_valid = sorted(
        valid_indices, key=lambda i: (float(pvs[i]), i),
    )
    sorted_p = [float(pvs[i]) for i in sorted_valid]

    # Walk from the largest rank to the smallest, taking the running
    # min of (m/rank) * p_(rank).  Clamp to [0, 1] only after the
    # running-min step — clamping in place would discard a smaller
    # later running-min that the earlier rank should inherit.
    adj_sorted: list[float] = [0.0] * m
    running_min = math.inf
    for k_zero in range(m - 1, -1, -1):
        rank = k_zero + 1  # 1-indexed
        candidate = (m / rank) * sorted_p[k_zero]
        if candidate < running_min:
            running_min = candidate
        adj_sorted[k_zero] = 1.0 if running_min > 1.0 else running_min

    # Restore original index positions and label discoveries.
    num_discoveries = 0
    for sorted_pos, original_idx in enumerate(sorted_valid):
        adj = adj_sorted[sorted_pos]
        adjusted[original_idx] = adj
        is_discovery = adj <= alpha_f
        discoveries[original_idx] = is_discovery
        if is_discovery:
            num_discoveries += 1

    return {
        "adjusted":        adjusted,
        "discoveries":     discoveries,
        "num_discoveries": num_discoveries,
        "m":               m,
        "alpha":           alpha_f,
    }
