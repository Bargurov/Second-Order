"""Small-sample robustness diagnostics for event-study readouts.

Pure stdlib (``math`` only).  No DB, no provider, no numpy, no scipy, no LLM,
no filesystem.  Mirrors :mod:`stats.p_values` / :mod:`stats.event_study` in
keeping the surface tiny and dependency-free.

These are **descriptive supplements** to the existing characterization, not new
discoveries and not a significance verdict:

  * :func:`exact_sign_test` — exact binomial sign test (``p=0.5`` null: "no
    directional abnormal tendency").  Run on market-adjusted abnormal-return
    SIGNS, where a fair-coin null is defensible — NOT on prediction-skewed
    support/contradiction outcomes (those keep the marginal-preserving
    permutation baseline).
  * :func:`rank_test_summary` — Wilcoxon signed-rank.  Adds a
    SYMMETRY-ABOUT-ZERO assumption the data may not satisfy, so it is a
    different lens, not strictly "more robust" than the sign test.  Exact
    enumeration for small n; continuity-corrected normal approximation above
    a cap.
  * :func:`window_overlap_summary` — event-window overlap disclosure.  This is
    the actual hardening: overlapping windows break the independence the sign /
    rank / bootstrap readouts assume, so the overlap summary is the qualifier
    that must travel WITH any p-value.
  * :func:`sar_convention_summary` — audits the SAR convention (compounded BHAR
    numerator over additive daily-sigma denominator) by recomputing SAR with
    the additive CAR numerator and reporting the per-horizon gap.  Report-only:
    it changes no event-study math.

No p-value is emitted without its method label and denominator (``n``).  No
single-event significance is claimed.  The closed Phase 1 / Phase 2 FDR pools
are neither read nor implied.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date as _date
from typing import Any, Iterable, Sequence

__all__ = (
    "exact_sign_test",
    "rank_test_summary",
    "window_overlap_summary",
    "independent_window_summary",
    "independent_window_diagnostic",
    "sar_convention_summary",
    "build_diagnostics_block",
    "build_overlap_disclosure",
    "ROBUST_DIAGNOSTICS_NON_CLAIMS",
    "OVERLAP_DISCLOSURE_CAVEAT",
    "MIN_INDEPENDENT_WINDOW_GATE",
    "INDEPENDENT_WINDOW_GATE_SOURCE",
)


_SQRT2 = math.sqrt(2.0)
_VALID_ALTERNATIVES: frozenset[str] = frozenset({"two-sided", "greater", "less"})


ROBUST_DIAGNOSTICS_NON_CLAIMS: tuple[str, ...] = (
    "Descriptive supplements to the existing characterization - not new "
    "discoveries, not a trading signal, not a measure of edge.",
    "Sign and rank tests assume independent observations; overlapping event "
    "windows (see the overlap summary) violate that, so these p-values "
    "understate uncertainty and are NOT significance claims.",
    "The exact sign test uses a p=0.5 null ('no directional abnormal "
    "tendency'); it is distinct from - and weaker than - the "
    "marginal-preserving permutation baseline reported alongside it.",
    "No single-event significance is claimed at any horizon.",
    "The SAR-convention note audits an existing point-estimate convention; no "
    "event-study math is changed.",
    "Separate from the closed Phase 1 / Phase 2 FDR pools; no pool q-values are "
    "used or implied.",
)


# ---------------------------------------------------------------------------
# Exact binomial sign test
# ---------------------------------------------------------------------------


def _coerce_signs(values: Iterable[Any]) -> tuple[int, int, int]:
    """Return ``(n_pos, n_neg, n_zero)`` over finite numeric values.

    Non-numeric / non-finite entries are skipped.  Exact zeros are counted
    separately and excluded from the effective sample (sign-test convention).
    """
    n_pos = n_neg = n_zero = 0
    for v in values if values is not None else []:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        x = float(v)
        if not math.isfinite(x):
            continue
        if x > 0.0:
            n_pos += 1
        elif x < 0.0:
            n_neg += 1
        else:
            n_zero += 1
    return n_pos, n_neg, n_zero


def _binom_sign_p(k: int, n: int, alternative: str) -> float:
    """Exact binomial tail p-value at ``p=0.5`` for ``k`` of ``n`` positive."""
    total = float(1 << n)  # 2**n
    upper = sum(math.comb(n, i) for i in range(k, n + 1)) / total
    lower = sum(math.comb(n, i) for i in range(0, k + 1)) / total
    if alternative == "greater":
        return upper
    if alternative == "less":
        return lower
    return min(1.0, 2.0 * min(lower, upper))


def exact_sign_test(
    values: Iterable[Any],
    *,
    alternative: str = "two-sided",
    min_n: int = 2,
) -> dict[str, Any]:
    """Exact binomial sign test over the signs of ``values``.

    Null: each nonzero observation is positive with probability 0.5 — "no
    directional abnormal tendency".  Returns a dict with ``status`` ∈
    ``{ok, insufficient_n, all_zero}``, the sign counts, ``p_value`` (``None``
    when no test is possible), ``method`` and ``alternative`` labels, and the
    null description.  Raises :class:`ValueError` on an unknown ``alternative``.
    """
    if not isinstance(alternative, str) or alternative not in _VALID_ALTERNATIVES:
        raise ValueError(
            f"alternative must be one of {sorted(_VALID_ALTERNATIVES)!r}; "
            f"got {alternative!r}",
        )
    n_pos, n_neg, n_zero = _coerce_signs(values)
    n = n_pos + n_neg
    base: dict[str, Any] = {
        "n": n,
        "n_pos": n_pos,
        "n_neg": n_neg,
        "n_zero": n_zero,
        "statistic": n_pos,
        "method": "exact_binomial_sign_test",
        "alternative": alternative,
        "null": "p=0.5 (no directional abnormal tendency)",
    }
    if n == 0:
        return {**base, "status": "all_zero" if n_zero > 0 else "insufficient_n",
                "p_value": None}
    p = _binom_sign_p(n_pos, n, alternative)
    return {**base, "status": "ok" if n >= min_n else "insufficient_n",
            "p_value": p}


# ---------------------------------------------------------------------------
# Wilcoxon signed-rank
# ---------------------------------------------------------------------------


def _average_ranks(values: Sequence[float]) -> list[float]:
    """1-based ranks of ``values`` ascending, averaging tied positions."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + 1 + j + 1) / 2.0  # positions i..j → 1-based ranks i+1..j+1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _wilcoxon_exact_two_sided(ranks: Sequence[float], w_obs: float) -> float:
    """Exact two-sided signed-rank p via the W+ distribution over 2^n signs.

    Built by DP over achievable rank sums (not literal 2^n enumeration), so it
    stays cheap even at the enumeration cap.
    """
    dist: dict[float, int] = {0.0: 1}
    for r in ranks:
        nd: dict[float, int] = defaultdict(int)
        for s, c in dist.items():
            nd[s] += c          # this rank assigned a negative sign
            nd[s + r] += c      # this rank assigned a positive sign
        dist = dict(nd)
    total = float(1 << len(ranks))
    eps = 1e-9
    upper = sum(c for s, c in dist.items() if s >= w_obs - eps) / total
    lower = sum(c for s, c in dist.items() if s <= w_obs + eps) / total
    return min(1.0, 2.0 * min(lower, upper))


def _wilcoxon_normal_two_sided(ranks: Sequence[float], w_obs: float) -> float:
    """Continuity-corrected normal-approximation two-sided signed-rank p.

    ``Var(W+) = (1/4) * sum(rank^2)`` is the tie-adjusted variance (each rank
    enters W+ with probability 1/2 independently under the null).
    """
    mean = sum(ranks) / 2.0
    var = sum(r * r for r in ranks) / 4.0
    if var <= 0.0:
        return 1.0
    z = (abs(w_obs - mean) - 0.5) / math.sqrt(var)
    if z < 0.0:
        z = 0.0
    return min(1.0, math.erfc(z / _SQRT2))


def rank_test_summary(
    values: Iterable[Any],
    *,
    exact_max_n: int = 20,
    min_n: int = 2,
) -> dict[str, Any]:
    """Wilcoxon signed-rank summary over ``values`` (symmetry-about-zero null).

    Drops exact zeros (signed-rank convention).  Returns ``status`` ∈
    ``{ok, insufficient_n, all_zero}``, ``n``, ``n_zero``, ``w_plus``,
    ``p_value``, ``method`` (``exact_signed_rank`` for ``n <= exact_max_n`` else
    ``normal_approx_signed_rank``), and the disclosed ``assumption``.
    """
    nonzero: list[float] = []
    n_zero = 0
    for v in values if values is not None else []:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        x = float(v)
        if not math.isfinite(x):
            continue
        if x == 0.0:
            n_zero += 1
        else:
            nonzero.append(x)
    n = len(nonzero)
    base: dict[str, Any] = {
        "n": n,
        "n_zero": n_zero,
        "alternative": "two-sided",
        "assumption": "symmetry_about_zero",
    }
    if n == 0:
        return {**base, "status": "all_zero" if n_zero > 0 else "insufficient_n",
                "w_plus": None, "p_value": None, "method": None}

    ranks = _average_ranks([abs(x) for x in nonzero])
    w_plus = sum(r for x, r in zip(nonzero, ranks) if x > 0.0)
    if n <= exact_max_n:
        p = _wilcoxon_exact_two_sided(ranks, w_plus)
        method = "exact_signed_rank"
    else:
        p = _wilcoxon_normal_two_sided(ranks, w_plus)
        method = "normal_approx_signed_rank"
    return {**base, "status": "ok" if n >= min_n else "insufficient_n",
            "w_plus": float(w_plus), "p_value": p, "method": method}


# ---------------------------------------------------------------------------
# Event-window overlap disclosure
# ---------------------------------------------------------------------------


def window_overlap_summary(
    start_ordinals: Iterable[Any],
    *,
    window_length: int,
) -> dict[str, Any]:
    """Overlap disclosure for event windows ``[start, start + window_length)``.

    ``start_ordinals`` are integer day positions (e.g. ordinal calendar days).
    Returns ``status`` ∈ ``{ok, insufficient_n}``, ``n_windows``,
    ``window_length``, ``overlapping_pairs`` (count of intersecting pairs),
    ``max_concurrent`` (peak windows covering any instant), and
    ``fraction_in_overlap`` (share of windows that intersect ≥1 other).  Raises
    :class:`ValueError` for a non-positive ``window_length``.
    """
    if isinstance(window_length, bool) or not isinstance(window_length, int):
        raise ValueError(
            f"window_length must be a positive int; got {window_length!r}",
        )
    if window_length <= 0:
        raise ValueError(
            f"window_length must be positive; got {window_length!r}",
        )

    starts: list[int] = []
    for s in start_ordinals if start_ordinals is not None else []:
        if isinstance(s, bool) or not isinstance(s, (int, float)):
            continue
        if isinstance(s, float) and not s.is_integer():
            continue
        starts.append(int(s))

    n = len(starts)
    base: dict[str, Any] = {"n_windows": n, "window_length": int(window_length)}
    if n == 0:
        return {**base, "status": "insufficient_n", "overlapping_pairs": 0,
                "max_concurrent": 0, "fraction_in_overlap": 0.0}

    intervals = [(s, s + window_length) for s in starts]
    overlaps = [False] * n
    pairs = 0
    for i in range(n):
        a0, a1 = intervals[i]
        for j in range(i + 1, n):
            b0, b1 = intervals[j]
            if a0 < b1 and b0 < a1:  # half-open intersection
                pairs += 1
                overlaps[i] = True
                overlaps[j] = True

    # Sweep for peak concurrency.  At a shared coordinate an end (-1) is
    # processed before a start (+1) so abutting half-open windows don't count
    # as concurrent.
    sweep: list[tuple[int, int]] = []
    for s, e in intervals:
        sweep.append((s, 1))
        sweep.append((e, -1))
    sweep.sort(key=lambda t: (t[0], t[1]))
    cur = mx = 0
    for _, d in sweep:
        cur += d
        if cur > mx:
            mx = cur

    return {**base, "status": "ok", "overlapping_pairs": pairs,
            "max_concurrent": mx,
            "fraction_in_overlap": sum(1 for o in overlaps if o) / n}


# ---------------------------------------------------------------------------
# Independent-window capacity diagnostic (C1) — additive, descriptive only.
# Turns the qualitative overlap caveat into concrete numbers WITHOUT changing
# any existing field, running cohort inference, or adding p-values.
# ---------------------------------------------------------------------------

MIN_INDEPENDENT_WINDOW_GATE: int = 8
INDEPENDENT_WINDOW_GATE_SOURCE: str = (
    "stats/METHODOLOGY.md - 'Cohort inference - currently blocked' criteria: "
    "at least 8 independent shocks (distinct underlying events)."
)
INDEPENDENT_WINDOW_INTERPRETATION: str = (
    "max_non_overlapping_windows is the independent-window capacity at this "
    "horizon: the size of the largest set of mutually non-overlapping "
    "forward windows (greedy earliest-finish interval scheduling, optimal "
    "for this problem). It is an upper-bound independent-shock count under "
    "the window-overlap criterion alone - meeting the gate does not by "
    "itself unblock cohort inference, because the methodology's other gates "
    "(distinct underlying events, mechanism_family labels, a predeclared "
    "denominator and exclusion list, a fresh self-contained FDR scope) "
    "still bind."
)
INDEPENDENT_WINDOW_NON_CLAIM: str = (
    "Diagnostic only: quantifies overlap/dependence pressure on the nominal "
    "n. It is an upper-bound count of mutually non-overlapping windows, not "
    "a true statistical effective sample size; it runs no cohort inference, "
    "adds no p-value or CI, does not validate any mechanism, changes no FDR "
    "scope, and does not authorize pooling."
)


def independent_window_summary(
    start_ordinals: Iterable[Any],
    *,
    window_length: int,
) -> dict[str, Any]:
    """Independent-window capacity over half-open windows ``[s, s + L)``.

    Same window convention and input coercion as
    :func:`window_overlap_summary`: ``start_ordinals`` are integer day
    positions, ``window_length`` is in the same day units (the callers'
    calendar-day proxy caveat for trading-day horizons applies unchanged).

    Returns ``nominal_n``, ``overlap_cluster_count`` /
    ``largest_overlap_cluster_size`` (connected components of the pairwise
    window-overlap graph - for equal-length windows two windows overlap iff
    their starts differ by less than ``window_length``, so components are
    exactly the runs of sorted starts whose consecutive gaps are below
    ``window_length``), and ``max_non_overlapping_windows`` (greedy
    earliest-finish interval scheduling, the classical optimum). Raises
    :class:`ValueError` for a non-positive ``window_length``.
    """
    if isinstance(window_length, bool) or not isinstance(window_length, int):
        raise ValueError(
            f"window_length must be a positive int; got {window_length!r}",
        )
    if window_length <= 0:
        raise ValueError(
            f"window_length must be positive; got {window_length!r}",
        )

    starts: list[int] = []
    for s in start_ordinals if start_ordinals is not None else []:
        if isinstance(s, bool) or not isinstance(s, (int, float)):
            continue
        if isinstance(s, float) and not s.is_integer():
            continue
        starts.append(int(s))

    n = len(starts)
    base: dict[str, Any] = {"nominal_n": n,
                            "window_length": int(window_length)}
    if n == 0:
        return {**base, "status": "insufficient_n",
                "overlap_cluster_count": 0,
                "largest_overlap_cluster_size": 0,
                "max_non_overlapping_windows": 0}

    starts.sort()

    # Connected overlap clusters: split sorted starts wherever the gap to the
    # previous start is >= window_length (no edge can cross such a gap).
    clusters = 1
    largest = cur = 1
    for prev, nxt in zip(starts, starts[1:]):
        if nxt - prev < window_length:
            cur += 1
        else:
            clusters += 1
            cur = 1
        if cur > largest:
            largest = cur

    # Maximum mutually non-overlapping windows: greedy earliest finish.
    count = 1
    last_end = starts[0] + window_length
    for s in starts[1:]:
        if s >= last_end:
            count += 1
            last_end = s + window_length

    return {**base, "status": "ok",
            "overlap_cluster_count": clusters,
            "largest_overlap_cluster_size": largest,
            "max_non_overlapping_windows": count}


def independent_window_diagnostic(
    start_ordinals: Iterable[Any],
    *,
    window_length: int,
) -> dict[str, Any]:
    """:func:`independent_window_summary` plus the methodology gate fields.

    The gate value comes from the existing cohort-inference criteria in
    ``stats/METHODOLOGY.md`` (">= 8 independent shocks"); it is reported, not
    invented. Meeting it never unblocks cohort inference by itself - see
    ``interpretation_note`` / ``non_claim``.
    """
    out = independent_window_summary(start_ordinals,
                                     window_length=window_length)
    out["min_independent_window_gate"] = MIN_INDEPENDENT_WINDOW_GATE
    out["gate_source"] = INDEPENDENT_WINDOW_GATE_SOURCE
    out["meets_min_independent_window_gate"] = (
        out["max_non_overlapping_windows"] >= MIN_INDEPENDENT_WINDOW_GATE
    )
    out["interpretation_note"] = INDEPENDENT_WINDOW_INTERPRETATION
    out["non_claim"] = INDEPENDENT_WINDOW_NON_CLAIM
    return out


# ---------------------------------------------------------------------------
# Overlap disclosure — reusable across reports (readiness, placebo, baseline)
# ---------------------------------------------------------------------------

OVERLAP_DISCLOSURE_CAVEAT: str = (
    "Overlapping event windows violate the independence that cross-event "
    "sign, rank, and placebo readouts assume, so those readouts overstate "
    "certainty. This is a descriptive independence caveat, not a significance "
    "statistic."
)


def _date_ordinal(value: Any) -> int | None:
    """Ordinal day for an ISO ``YYYY-MM-DD`` (or longer) string, else ``None``."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _date.fromisoformat(value.strip()[:10]).toordinal()
    except (ValueError, TypeError):
        return None


def build_overlap_disclosure(
    event_dates: Iterable[Any],
    *,
    horizons: Sequence[int] = (1, 5, 20),
    denominator_label: str,
    caveat: str | None = None,
) -> dict[str, Any]:
    """Per-horizon event-window overlap disclosure over ``event_dates``.

    ``event_dates`` is an iterable of ISO date strings for the events that
    would actually be pooled into a cross-event statistic (the caller's own
    universe — reuse the report's denominator, do not invent a third one).
    Unparseable / missing dates are dropped and counted in ``n_without_date``;
    ``n_distinct_event_dates`` exposes how many windows share a date (those are
    identically overlapping by construction). The window length per horizon is
    the horizon in days, a calendar-day proxy for the trading-day horizon
    (errs toward UNDERstating overlap). Each horizon entry is a
    :func:`window_overlap_summary` block. The ``caveat`` travels with the block
    so any p-value or null comparison carries its independence qualifier.
    """
    ordinals: list[int] = []
    distinct: set[int] = set()
    n_without = 0
    for d in event_dates if event_dates is not None else []:
        o = _date_ordinal(d)
        if o is None:
            n_without += 1
        else:
            ordinals.append(o)
            distinct.add(o)

    horizons_out: dict[str, Any] = {}
    for h in horizons:
        block = window_overlap_summary(ordinals, window_length=int(h))
        # C1 additive: independent-window capacity beside the overlap
        # summary. Existing fields are untouched.
        block["independent_window_diagnostic"] = independent_window_diagnostic(
            ordinals, window_length=int(h),
        )
        horizons_out[str(int(h))] = block

    return {
        "denominator":            denominator_label,
        "n_with_date":            len(ordinals),
        "n_without_date":         n_without,
        "n_distinct_event_dates": len(distinct),
        "window_length_basis":    "calendar_days_proxy_for_trading_day_horizon",
        "horizons":               horizons_out,
        "caveat":                 caveat or OVERLAP_DISCLOSURE_CAVEAT,
    }


# ---------------------------------------------------------------------------
# SAR convention audit (report-only)
# ---------------------------------------------------------------------------


def sar_convention_summary(rows: Iterable[Any]) -> dict[str, Any]:
    """Audit the SAR convention without changing any event-study math.

    The engine's SAR is ``abnormal_return (BHAR, compounded) / (sigma * sqrt h)``
    while the denominator scales the additive daily-AR sigma.  For each input
    row with finite ``sigma_ar_daily > 0`` this recomputes ``sar_car = car /
    (sigma * sqrt h)`` (additive-CAR numerator); the convention gap is
    ``sar_delta = sar_bhar - sar_car`` — the level that would move a p-value.

    Rows are grouped by horizon and aggregated (``n``, ``mean_sar_delta``,
    ``mean_abs_sar_delta``, ``max_abs_sar_delta``) so the report shows whether
    the convention matters across the eligible set, with a per-horizon
    ``example`` row preserved for spot-checking.  Returns ``status`` ∈
    ``{ok, not_applicable}``.
    """
    by_horizon: dict[int, list[dict[str, float]]] = defaultdict(list)
    for r in rows if rows is not None else []:
        if not isinstance(r, dict):
            continue
        try:
            hz = int(r.get("horizon"))
            ar = float(r.get("abnormal_return"))
            car = float(r.get("car"))
            sigma = float(r.get("sigma_ar_daily"))
        except (TypeError, ValueError):
            continue
        if hz <= 0 or sigma <= 0.0:
            continue
        if not (math.isfinite(ar) and math.isfinite(car) and math.isfinite(sigma)):
            continue
        denom = sigma * math.sqrt(hz)
        sar_bhar = ar / denom
        sar_car = car / denom
        by_horizon[hz].append({
            "sar_bhar": sar_bhar,
            "sar_car": sar_car,
            "sar_delta": sar_bhar - sar_car,
            "ar_minus_car": ar - car,
        })

    base: dict[str, Any] = {
        "numerator_convention": "bhar_compounded",
        "denominator_convention": "additive_daily_sigma_scaled_by_sqrt_h",
        "conventions_match": False,
        "note": (
            "SAR numerator is the compounded buy-and-hold abnormal return "
            "(BHAR); the denominator scales the additive daily-AR sigma by "
            "sqrt(h). sar_car recomputes SAR with the additive CAR numerator so "
            "the convention gap (sar_delta) is auditable. The mismatch is "
            "small at horizons <= 20d. Report-only - no event-study math is "
            "changed."
        ),
    }
    if not by_horizon:
        return {**base, "status": "not_applicable", "per_horizon": []}

    per_horizon: list[dict[str, Any]] = []
    for hz in sorted(by_horizon):
        items = by_horizon[hz]
        deltas = [it["sar_delta"] for it in items]
        n = len(deltas)
        per_horizon.append({
            "horizon": hz,
            "n": n,
            "mean_sar_delta": sum(deltas) / n,
            "mean_abs_sar_delta": sum(abs(d) for d in deltas) / n,
            "max_abs_sar_delta": max(abs(d) for d in deltas),
            "example": dict(items[0]),
        })
    return {**base, "status": "ok", "per_horizon": per_horizon}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def build_diagnostics_block(
    per_horizon: dict[int, dict[str, Any]],
    *,
    benchmark: str = "SPY",
) -> dict[str, Any]:
    """Assemble the per-horizon diagnostics block from pre-extracted data.

    ``per_horizon[h]`` carries ``ar_values`` (the eligible abnormal-return
    floats — reuse the report's own eligible set so ``n`` matches its
    ``eligible`` count, never a third denominator), ``window_starts`` (day
    ordinals for the same eligible events), ``window_length`` (days), and
    ``es_rows`` (a list of per-event ``{abnormal_return, car, sigma_ar_daily}``
    dicts for the SAR audit).  The overlap summary is co-located with the
    sign/rank p-values as their independence qualifier.
    """
    horizons_out: dict[str, Any] = {}
    sar_rows: list[dict[str, Any]] = []
    for h in sorted(per_horizon or {}):
        spec = per_horizon[h] or {}
        ar_values = spec.get("ar_values") or []
        window_starts = spec.get("window_starts") or []
        wl = int(spec.get("window_length") or 1)
        horizons_out[str(h)] = {
            "horizon": h,
            "sign_test": exact_sign_test(ar_values),
            "rank_test": rank_test_summary(ar_values),
            "overlap": window_overlap_summary(window_starts, window_length=wl),
            # C1 additive: independent-window capacity beside the overlap
            # qualifier. Descriptive only; existing fields untouched.
            "independent_window_diagnostic": independent_window_diagnostic(
                window_starts, window_length=wl,
            ),
        }
        for es in spec.get("es_rows") or []:
            if not isinstance(es, dict):
                continue
            sar_rows.append({
                "horizon": h,
                "abnormal_return": es.get("abnormal_return"),
                "car": es.get("car"),
                "sigma_ar_daily": es.get("sigma_ar_daily"),
            })

    return {
        "benchmark": benchmark,
        "horizons": horizons_out,
        "sar_convention": sar_convention_summary(sar_rows),
        "non_claims": list(ROBUST_DIAGNOSTICS_NON_CLAIMS),
    }
