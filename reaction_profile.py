"""Pure reaction-profile composer.

Per-ticker primitive fields computed from a price-bar series.  See
``docs/reaction_profile_design.md`` for the field contract, anchor
conventions, and edge-case mapping.

Pure composer
-------------
* No I/O.  All inputs are bar sequences supplied by the caller.
* No clock reads, no provider calls, no DB writes.
* Never raises; malformed input collapses to the empty profile shape.
* Output dict has a stable key set across every input shape, so
  consumers can rely on field presence (values may be None /
  ``"insufficient"``).
"""

from __future__ import annotations

from typing import Any, Optional, Sequence


# ---------------------------------------------------------------------------
# Pinned constants — see docs/reaction_profile_design.md §3 / §7
# ---------------------------------------------------------------------------

# Per-horizon noise floors, percent.  1d/5d/20d mirror
# ``validation_evidence._NOISE_*_PCT`` so the two layers agree on what
# counts as below-noise for the same horizon.  60d is added per design;
# starting value, not yet calibrated.
_NOISE_1D_PCT:  float = 0.5
_NOISE_5D_PCT:  float = 1.0
_NOISE_20D_PCT: float = 2.0
_NOISE_60D_PCT: float = 3.0

# Retention threshold for fade_or_hold_label.  When |final|/|peak| is at
# or above this fraction (and sign hasn't flipped), the move "held".
# Pinned in one place so calibration changes happen here, not inline.
_FADE_HOLD_THRESHOLD: float = 0.7

# Storage parity with ``market_check.py`` — every percent rounded to 2dp.
_ROUND_DP: int = 2

# Horizon registry: (suffix, n_bars, noise_floor_pct).
_HORIZONS: tuple[tuple[str, int, float], ...] = (
    ("1d",   1, _NOISE_1D_PCT),
    ("5d",   5, _NOISE_5D_PCT),
    ("20d", 20, _NOISE_20D_PCT),
    ("60d", 60, _NOISE_60D_PCT),
)

# Horizons that carry peak / time-to-peak / fade-or-hold readings.  The
# 1d horizon has only one forward bar so a "peak" within the window is
# trivially that bar — no decision to make.
_PEAK_HORIZONS: tuple[str, ...] = ("5d", "20d", "60d")

# Public vocabularies — exhaustive, mutually exclusive.
FADE_OR_HOLD_LABELS: tuple[str, ...] = (
    "hold", "fade", "reverse", "flat", "insufficient",
)

REACTION_PROFILE_BASES: tuple[str, ...] = (
    "forward_anchored", "same_day_fallback", "stale", "unscorable",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_finite_number(v: Any) -> bool:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return False
    f = float(v)
    if f != f:
        return False
    if f == float("inf") or f == float("-inf"):
        return False
    return True


def _pct_from_anchor(closes: Sequence[float], n: int) -> Optional[float]:
    """Percent change from ``closes[0]`` to ``closes[n]``.

    None when the series is too short, the anchor is non-positive /
    non-finite, or the target bar is non-finite.
    """
    if not isinstance(closes, (list, tuple)):
        return None
    if len(closes) < n + 1:
        return None
    anchor = closes[0]
    if not _is_finite_number(anchor) or anchor == 0:
        return None
    target = closes[n]
    if not _is_finite_number(target):
        return None
    return round((float(target) / float(anchor) - 1.0) * 100.0, _ROUND_DP)


def _peak_in_window(
    closes: Sequence[float], n: int,
) -> tuple[Optional[float], Optional[int]]:
    """Largest ``|close[i] - anchor|`` for ``i in 1..n``.

    Returns ``(peak_move_pct, time_to_peak_bars)`` or ``(None, None)``
    when the window is unscorable (insufficient bars or invalid anchor).
    Ties on absolute deviation go to the earliest bar.
    """
    if not isinstance(closes, (list, tuple)):
        return (None, None)
    if len(closes) < n + 1:
        return (None, None)
    anchor = closes[0]
    if not _is_finite_number(anchor) or anchor == 0:
        return (None, None)

    best_idx: Optional[int] = None
    best_abs: float = -1.0
    for i in range(1, n + 1):
        c = closes[i]
        if not _is_finite_number(c):
            continue
        diff_abs = abs(float(c) - float(anchor))
        if diff_abs > best_abs:  # strict > preserves earliest-on-tie
            best_abs = diff_abs
            best_idx = i

    if best_idx is None:
        return (None, None)
    peak_pct = round(
        (float(closes[best_idx]) / float(anchor) - 1.0) * 100.0,
        _ROUND_DP,
    )
    return (peak_pct, best_idx)


def _fade_or_hold_label(
    peak: Optional[float], final: Optional[float], noise: float,
) -> str:
    """Decision table per docs/reaction_profile_design.md §3.5.

    Order matters:
      1. insufficient — peak or final missing
      2. flat        — |peak| < noise
      3. reverse     — peak and final disagree on sign (final == 0 does
                       NOT count as a sign flip; falls through to fade)
      4. hold        — |final|/|peak| >= _FADE_HOLD_THRESHOLD
      5. fade        — otherwise
    """
    if peak is None or final is None:
        return "insufficient"
    if abs(peak) < noise:
        return "flat"
    if (peak > 0 and final < 0) or (peak < 0 and final > 0):
        return "reverse"
    if abs(peak) == 0:
        return "flat"
    if abs(final) / abs(peak) >= _FADE_HOLD_THRESHOLD:
        return "hold"
    return "fade"


def _empty_profile() -> dict[str, Any]:
    """Stable key set with all numeric fields nulled and labels set to
    ``"insufficient"``.  Basis is overwritten by the caller."""
    out: dict[str, Any] = {}
    for suffix, _n, _noise in _HORIZONS:
        out[f"return_{suffix}"] = None
        out[f"benchmark_relative_return_{suffix}"] = None
    for suffix in _PEAK_HORIZONS:
        out[f"peak_move_{suffix}"] = None
        out[f"time_to_peak_{suffix}"] = None
        out[f"fade_or_hold_label_{suffix}"] = "insufficient"
    out["reaction_profile_basis"] = "unscorable"
    return out


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def compute_reaction_profile(
    closes: Optional[Sequence[float]],
    *,
    benchmark_closes: Optional[Sequence[float]] = None,
    stale: bool = False,
    same_day_fallback: bool = False,
    benchmark_quarantined_horizons: Optional[set[str]] = None,
) -> dict[str, Any]:
    """Compute the per-ticker reaction profile.

    ``closes[0]`` is the anchor close (event-date close in the normal
    forward-anchored mode; prior-day close in same_day_fallback mode).
    ``closes[1:]`` are subsequent session closes.

    ``benchmark_closes`` follows the same anchor convention; when None
    or too short, the matching ``benchmark_relative_return_*`` field is
    None.

    ``stale`` collapses the profile to the stale shape — every
    forward-looking field is None, basis = ``"stale"``.  Set by callers
    that have detected a delisted / halted ticker before invoking the
    composer.

    ``same_day_fallback`` indicates the anchor is the prior session's
    close rather than the event close; only ``return_1d`` (and the
    matching ``benchmark_relative_return_1d``) populate.

    ``benchmark_quarantined_horizons`` names horizon suffixes
    (``{"1d","5d","20d","60d"}``) whose benchmark print is quarantined;
    the matching ``benchmark_relative_return_*`` field is nulled
    regardless of the otherwise-computable value.
    """
    quarantined = benchmark_quarantined_horizons or set()

    out = _empty_profile()

    if not isinstance(closes, (list, tuple)) or len(closes) < 2:
        out["reaction_profile_basis"] = "unscorable"
        return out

    if stale:
        out["reaction_profile_basis"] = "stale"
        return out

    if same_day_fallback:
        out["reaction_profile_basis"] = "same_day_fallback"
        r1 = _pct_from_anchor(closes, 1)
        out["return_1d"] = r1
        if (
            "1d" not in quarantined
            and isinstance(benchmark_closes, (list, tuple))
            and len(benchmark_closes) >= 2
        ):
            b1 = _pct_from_anchor(benchmark_closes, 1)
            if r1 is not None and b1 is not None:
                out["benchmark_relative_return_1d"] = round(
                    r1 - b1, _ROUND_DP,
                )
        return out

    out["reaction_profile_basis"] = "forward_anchored"

    bench_seq = (
        benchmark_closes if isinstance(benchmark_closes, (list, tuple))
        else None
    )

    for suffix, n, noise in _HORIZONS:
        ret = _pct_from_anchor(closes, n)
        out[f"return_{suffix}"] = ret

        if suffix not in quarantined and bench_seq is not None:
            bret = _pct_from_anchor(bench_seq, n)
            if ret is not None and bret is not None:
                out[f"benchmark_relative_return_{suffix}"] = round(
                    ret - bret, _ROUND_DP,
                )

        if suffix == "1d":
            continue
        peak, ttp = _peak_in_window(closes, n)
        out[f"peak_move_{suffix}"] = peak
        out[f"time_to_peak_{suffix}"] = ttp
        out[f"fade_or_hold_label_{suffix}"] = _fade_or_hold_label(
            peak, ret, noise,
        )

    return out
