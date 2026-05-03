"""Weighted-evidence classifier for per-ticker market validation.

Replaces the flat latest-day "notable move / flat / needs more evidence"
label with a read that weighs 1d / 5d / 20d returns, benchmark-relative
alpha, and volume confirmation into a single evidence verdict:

    * ``supportive``      — the tape materially backs the thesis direction.
    * ``mixed``           — signals disagree; conviction is unclear.
    * ``contradictory``   — the tape pushes against the thesis direction.
    * ``insufficient``    — too few horizons cleared noise for a call.

Design discipline
-----------------
* Pure composer.  No I/O.  Never raises on malformed input.
* Every threshold is a pinned module constant so calibrate_thresholds
  and EVALUATION.md can audit them in one place.
* Deterministic: same ticker record → same evidence dict.
* Does not overclaim.  The string vocabulary is ``supportive`` (not
  "validated"), ``mixed`` (not "ambiguous outcome"), and
  ``contradictory`` (not "falsified") — this layer is evidence, not
  proof.
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Pinned thresholds — see EVALUATION.md "Validation Evidence" section for
# the representative-fixture check that produced these.
# ---------------------------------------------------------------------------

# Per-horizon noise floors (absolute % return).  Below the floor the
# horizon is treated as unscorable — neither supportive nor against.
_NOISE_1D_PCT:  float = 0.5
_NOISE_5D_PCT:  float = 1.0
_NOISE_20D_PCT: float = 2.0

# Alpha (benchmark-relative) floor in percentage points.  Below this
# the alpha contribution is treated as noise.
_ALPHA_FLOOR_PP: float = 0.5

# Volume-ratio floor for a "volume confirms direction" bump.
_VOLUME_CONFIRM_RATIO: float = 1.5

# Horizon weights sum to 0.85; alpha + volume add 0.10 + 0.05 = 1.00
# at the theoretical maximum.  Weights are tilted so 5d / 20d dominate
# 1d — one-day moves are noisy reads of mechanism follow-through.
_W_1D:     float = 0.15
_W_5D:     float = 0.40
_W_20D:    float = 0.30
_W_ALPHA:  float = 0.10
_W_VOLUME: float = 0.05

# Per-persistence horizon weight profiles — the validation read is
# horizon-aware so the same ticker record produces a different verdict
# depending on the event it's attached to:
#
#   * ``transient`` / ``anticipation`` — the news is short-lived or
#     not yet realized, so the desk reads 1d/5d hardest and discounts
#     20d (a small 20d move is more likely drift than mechanism
#     transmission for a transient event).
#   * ``medium`` — the standard balanced read; 5d carries the most
#     weight but 20d still gets material credit for follow-through.
#   * ``structural`` — the news is a regime change.  1d/5d are noise
#     here; the read leans on 20d so a structural event isn't
#     judged by the first session's tape.
#
# Each profile sums to the same horizon budget (0.85) so the alpha
# (0.10) and volume (0.05) contributions stay calibrated.
_HORIZON_WEIGHTS_BY_PERSISTENCE: dict[str, tuple[float, float, float]] = {
    "transient":  (0.35, 0.35, 0.15),
    "medium":     (0.15, 0.40, 0.30),
    "structural": (0.10, 0.25, 0.50),
    "default":    (_W_1D, _W_5D, _W_20D),
}


def _normalize_persistence(
    persistence: Optional[str],
    stage: Optional[str],
) -> str:
    """Fold the LLM/UI persistence + stage vocabulary onto the three
    weight profile keys.  Returns one of
    ``{"transient", "medium", "structural", "default"}``.

    ``stage == "anticipation"`` always pulls toward the transient
    profile — an unrealized event hasn't transmitted yet, so weak 20d
    drift shouldn't tip the verdict regardless of the persistence label.

    Persistence synonyms accepted:
      * ``transient`` / ``low`` / ``short``
      * ``medium``
      * ``structural`` / ``persistent`` / ``high`` / ``long``
    """
    if isinstance(stage, str) and stage.strip().lower() == "anticipation":
        return "transient"
    if not isinstance(persistence, str):
        return "default"
    p = persistence.strip().lower()
    if p in ("transient", "low", "short"):
        return "transient"
    if p == "medium":
        return "medium"
    if p in ("structural", "persistent", "high", "long"):
        return "structural"
    return "default"

# Evidence bands on the weighted score in [-1.0, +1.0].
_BAND_SUPPORTIVE:    float = 0.35
_BAND_CONTRADICTORY: float = -0.35

# Minimum number of horizons that must clear noise before we commit to
# a supportive / contradictory / mixed verdict.  Below this we return
# ``insufficient``.
_MIN_SCORABLE_HORIZONS: int = 2

EVIDENCE_LABELS: tuple = (
    "supportive", "mixed", "contradictory", "insufficient",
)


# ---------------------------------------------------------------------------
# Asset-aware direction tables
# ---------------------------------------------------------------------------
# Inverse-direction tickers — their price moves opposite to the
# underlying they reference.  Treat a "beneficiary up" on these as a
# contradiction (the underlying moved down) and a "beneficiary down"
# as supportive.  Implementation: flip the role-based sign.
_INVERSE_DIRECTION_TICKERS: frozenset[str] = frozenset({
    # Inverse equity ETFs (one-times).
    "SH", "PSQ", "DOG",
    # Leveraged inverse equity ETFs.
    "SQQQ", "SPXU", "TZA", "SDOW",
    # Inverse bonds.
    "TBT",
    # Short-commodity ETFs (uncommon but show up via _LOSER_PROXY_MAP).
    "DUG", "GLL", "SCO", "SMN", "SKF", "YANG",
})

# Signal-only tickers — vol products and FX proxies.  These can't be
# validated through the role-based ``beneficiary up`` / ``loser down``
# heuristic because the asset's direction depends on what the
# underlying signal channel is doing, not on whether the LLM tagged
# the ticker as a beneficiary.  Validation must come through the
# named signal channel (vol / fx / equities / rates) or it's
# insufficient evidence — _direction_sign returns 0.
_SIGNAL_ONLY_TICKERS: frozenset[str] = frozenset({
    # Vol products.
    "VXX", "UVXY", "VIXY", "VIXM",
    # FX proxies.
    "UUP", "UDN", "FXE", "FXY", "FXA", "FXB", "FXC", "CEW", "CYB",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _direction_sign(
    role: Optional[str], value: float, *, symbol: Optional[str] = None,
) -> int:
    """Return +1 when the return aligns with the thesis role, -1 when
    against.  Returns 0 when role is missing / unknown.

    Asset-aware rules:
      * **Signal-only** symbols (vol / FX) return 0 — a simple
        role-direction read can't validate them; they need an explicit
        signal-channel expectation.
      * **Inverse-direction** symbols flip the role's sign — a
        beneficiary up on SH means the underlying went down, which
        contradicts (not confirms) a long-the-underlying thesis.
    """
    if not isinstance(role, str):
        return 0
    r = role.lower()
    sym = (symbol or "").strip().upper()

    # Signal-only: role-direction read isn't enough.
    if sym in _SIGNAL_ONLY_TICKERS:
        return 0

    if r == "beneficiary":
        sign = 1 if value > 0 else -1 if value < 0 else 0
    elif r == "loser":
        sign = 1 if value < 0 else -1 if value > 0 else 0
    else:
        return 0

    # Inverse-direction: flip the sign so a "beneficiary up" on an
    # inverse ETF reads as a contradiction.
    if sym in _INVERSE_DIRECTION_TICKERS:
        sign = -sign

    return sign


def _score_horizon(
    value: Optional[float], *, noise: float, weight: float,
    role: Optional[str], symbol: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Return a single-horizon contribution dict, or None when unscorable.

    ``value`` is the raw % return at the horizon.  Values below the
    noise floor or missing are unscorable — the caller skips them.
    """
    if value is None or not isinstance(value, (int, float)):
        return None
    if abs(float(value)) < noise:
        return None
    sign = _direction_sign(role, float(value), symbol=symbol)
    if sign == 0:
        return None
    return {
        "value":        round(float(value), 2),
        "in_direction": sign > 0,
        "contribution": round(weight * sign, 3),
        "weight":       weight,
    }


def _score_alpha(
    alpha: Optional[float], *, role: Optional[str],
    symbol: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    if alpha is None or not isinstance(alpha, (int, float)):
        return None
    if abs(float(alpha)) < _ALPHA_FLOOR_PP:
        return None
    sign = _direction_sign(role, float(alpha), symbol=symbol)
    if sign == 0:
        return None
    return {
        "value":        round(float(alpha), 2),
        "in_direction": sign > 0,
        "contribution": round(_W_ALPHA * sign, 3),
        "weight":       _W_ALPHA,
    }


def _score_volume(
    volume_ratio: Optional[float], *, net_sign: int,
) -> Optional[dict[str, Any]]:
    """Volume confirms the direction already implied by the horizons —
    so it only contributes when the horizon net-sign is non-zero."""
    if volume_ratio is None or not isinstance(volume_ratio, (int, float)):
        return None
    if float(volume_ratio) < _VOLUME_CONFIRM_RATIO:
        return None
    if net_sign == 0:
        return None
    return {
        "value":        round(float(volume_ratio), 2),
        "in_direction": net_sign > 0,
        "contribution": round(_W_VOLUME * net_sign, 3),
        "weight":       _W_VOLUME,
    }


# ---------------------------------------------------------------------------
# Public classifier
# ---------------------------------------------------------------------------

def classify_validation_evidence(
    record: Optional[dict[str, Any]],
    *,
    persistence: Optional[str] = None,
    stage: Optional[str] = None,
) -> dict[str, Any]:
    """Classify a ticker record into a weighted-evidence verdict.

    Accepts a dict with any of these keys (all optional):

      * ``role`` — ``"beneficiary"`` / ``"loser"``
      * ``return_1d``, ``return_5d``, ``return_20d``
      * ``relative_return_5d``  (primary alpha read against benchmark)
      * ``relative_return_20d`` (fallback alpha when 5d is missing)
      * ``volume_ratio``

    Optional kwargs ``persistence`` / ``stage`` shift the per-horizon
    weights so the same ticker record produces different verdicts
    depending on the event context (transient events lean on 1d/5d;
    structural events lean on 20d).  When neither is supplied the
    default balanced profile is used — preserving prior behaviour for
    callers that haven't been threaded through.

    Returns a dict with stable keys:

      * ``evidence_label``       — one of EVIDENCE_LABELS
      * ``evidence_score``       — weighted score in [-1, +1]
      * ``evidence_detail``      — short human-readable summary
      * ``evidence_components``  — per-axis contribution list
      * ``evidence_scored_horizons`` — count of horizons above noise
      * ``evidence_basis``       — ``"returns_and_alpha"`` / ``"returns_only"`` /
                                    ``"unscorable"``

    Never raises on malformed input.
    """
    empty = {
        "evidence_label":           "insufficient",
        "evidence_score":           0.0,
        "evidence_detail":          "No scorable data.",
        "evidence_components":      [],
        "evidence_scored_horizons": 0,
        "evidence_basis":           "unscorable",
    }
    if not isinstance(record, dict):
        return empty

    role = record.get("role")
    if not isinstance(role, str) or role.lower() not in ("beneficiary", "loser"):
        return {
            **empty,
            "evidence_detail": "Thesis role unknown; cannot assign direction.",
        }

    components: list[dict[str, Any]] = []

    profile_key = _normalize_persistence(persistence, stage)
    w1, w5, w20 = _HORIZON_WEIGHTS_BY_PERSISTENCE[profile_key]

    # Pull symbol once so per-asset direction rules (inverse / signal-
    # only) apply uniformly across every horizon and the alpha read.
    symbol = record.get("symbol") if isinstance(record.get("symbol"), str) else None

    h1 = _score_horizon(
        record.get("return_1d"),
        noise=_NOISE_1D_PCT, weight=w1, role=role, symbol=symbol,
    )
    h5 = _score_horizon(
        record.get("return_5d"),
        noise=_NOISE_5D_PCT, weight=w5, role=role, symbol=symbol,
    )
    h20 = _score_horizon(
        record.get("return_20d"),
        noise=_NOISE_20D_PCT, weight=w20, role=role, symbol=symbol,
    )

    horizon_specs = [("return_1d", h1), ("return_5d", h5), ("return_20d", h20)]
    scored_horizons = 0
    horizon_score = 0.0
    for axis, row in horizon_specs:
        if row is None:
            continue
        scored_horizons += 1
        horizon_score += row["contribution"]
        components.append({"axis": axis, **row})

    if scored_horizons < _MIN_SCORABLE_HORIZONS:
        return {
            "evidence_label":           "insufficient",
            "evidence_score":           round(horizon_score, 3),
            "evidence_detail":          (
                f"Only {scored_horizons} horizon(s) cleared noise "
                f"({_NOISE_1D_PCT}/{_NOISE_5D_PCT}/{_NOISE_20D_PCT}% floors)."
            ),
            "evidence_components":      components,
            "evidence_scored_horizons": scored_horizons,
            "evidence_basis":           "unscorable",
        }

    # Alpha contribution.  Prefer 5d alpha; fall back to 20d when 5d is
    # missing so a ticker with only long-horizon benchmark data still
    # gets the benchmark-relative read.
    alpha_value = record.get("relative_return_5d")
    alpha_axis = "relative_return_5d"
    if alpha_value is None:
        alpha_value = record.get("relative_return_20d")
        alpha_axis = "relative_return_20d"
    alpha_row = _score_alpha(alpha_value, role=role, symbol=symbol)
    if alpha_row is not None:
        components.append({"axis": alpha_axis, **alpha_row})

    total_score = horizon_score + (alpha_row["contribution"] if alpha_row else 0.0)
    net_sign = 1 if total_score > 0 else -1 if total_score < 0 else 0

    vol_row = _score_volume(record.get("volume_ratio"), net_sign=net_sign)
    if vol_row is not None:
        components.append({"axis": "volume_ratio", **vol_row})
        total_score += vol_row["contribution"]

    # Clamp to [-1, +1] so downstream consumers have a predictable scale.
    total_score = max(-1.0, min(1.0, total_score))
    total_score = round(total_score, 3)

    if total_score >= _BAND_SUPPORTIVE:
        label = "supportive"
    elif total_score <= _BAND_CONTRADICTORY:
        label = "contradictory"
    else:
        label = "mixed"

    basis = "returns_and_alpha" if alpha_row else "returns_only"
    detail = _compose_detail(label, total_score, components, scored_horizons)

    return {
        "evidence_label":           label,
        "evidence_score":           total_score,
        "evidence_detail":          detail,
        "evidence_components":      components,
        "evidence_scored_horizons": scored_horizons,
        "evidence_basis":           basis,
    }


# ---------------------------------------------------------------------------
# Detail prose
# ---------------------------------------------------------------------------

_AXIS_LABELS: dict[str, str] = {
    "return_1d":           "1d",
    "return_5d":           "5d",
    "return_20d":          "20d",
    "relative_return_5d":  "alpha 5d",
    "relative_return_20d": "alpha 20d",
    "volume_ratio":        "volume",
}


def _compose_detail(
    label: str,
    score: float,
    components: list[dict[str, Any]],
    scored_horizons: int,
) -> str:
    if not components:
        return f"{label} (score {score:+.2f}); no scorable axes."

    # Sort contribution-by-magnitude for the detail string — the
    # reader sees the strongest signal first.
    sorted_rows = sorted(
        components, key=lambda c: -abs(c.get("contribution") or 0.0),
    )
    bits: list[str] = []
    for c in sorted_rows:
        axis = _AXIS_LABELS.get(c["axis"], c["axis"])
        value = c.get("value")
        if axis == "volume":
            bits.append(f"vol {value:.1f}x")
            continue
        sign = "+" if (value is not None and value > 0) else ""
        bits.append(f"{axis} {sign}{value}%")
    summary = ", ".join(bits[:4])
    return f"{label} (score {score:+.2f}; {scored_horizons} horizons) - {summary}"
