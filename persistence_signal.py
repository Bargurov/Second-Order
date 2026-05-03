"""Pure persistence-lifecycle classifier.

Combines event age, persistence type, and revisit follow-through data to
produce a single "is this still playing out?" signal without touching the DB.

Signal statuses
---------------
  watching    — too early or no data yet
  active      — thesis holding within expected horizon
  fading      — returns declining or split signals
  resolved    — past horizon, or thesis clearly contradicted

Persistence horizons
--------------------
  transient   →  5d
  medium      → 20d
  structural  → 90d
  (default)   → 30d
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import event_age_policy

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

_HORIZON_DAYS: dict[str, int] = {
    "transient":  5,
    "medium":    20,
    "structural": 90,
}
_DEFAULT_HORIZON_DAYS: int = 30

# Return-trajectory thresholds (percentage points).  A delta between the
# thesis-aligned return at day-5 and day-20 snapshots that crosses these
# marks the move as building or fading.
_BUILDING_THRESHOLD_PP: float = 1.0   # +1pp gain day-5 → day-20 → building
_FADING_THRESHOLD_PP: float   = -1.5  # -1.5pp loss day-5 → day-20 → fading

# Direction-ratio cutoffs.  Above SUPPORT_HIGH → active; below SUPPORT_LOW → fading.
_SUPPORT_HIGH: float = 0.6
_SUPPORT_LOW:  float = 0.3

# Events newer than this (days) without revisit data get "watching" status.
_WATCHING_AGE_DAYS: int = 3


# ---------------------------------------------------------------------------
# Repricing-state thresholds (percentage points, equity-scale)
# ---------------------------------------------------------------------------
# Each threshold is validated empirically in tests.  Sign convention: all
# returns are "thesis-aligned" — a ticker's return is flipped by role so
# positive always means "thesis playing out".
#
# Noise floor under which we treat a return as indistinguishable from drift.
_REPRICING_NOISE_PP: float = 0.30

# A "gap" is a day-1 thesis-aligned move at or above this magnitude (in pp).
# Below this the move is too small to anchor a gap-and-hold read.
_GAP_SIGNIFICANCE_PP: float = 1.00

# Hold band: r5/r1 must fall in [low, high] for the 5d move to be treated
# as "held" relative to day 1.  Outside the band is retrace or extension.
_HOLD_BAND_LOW:  float = 0.70
_HOLD_BAND_HIGH: float = 1.30

# Retrace: r5 in same direction as r1 but has given back material ground.
_RETRACE_MAX_FRACTION: float = 0.60   # |r5| / |r1| ≤ 0.60 → retrace

# Second leg: r20 extends materially past the 5d reading in the same sign.
_SECOND_LEG_MULT: float = 1.30        # |r20| ≥ |r5| * 1.30

# Grind: small r1 but substantive r5 follow-through in the thesis direction.
_GRIND_R1_MAX_PP: float = 0.80        # r1 below this looks "unanchored"
_GRIND_R5_MIN_PP: float = 1.00        # r5 must clear this magnitude

# Invalidation: 20d reading is materially against the thesis (post-horizon
# direction reversed, not just paused).
_INVALIDATION_FLOOR_PP: float = -0.80


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _horizon_for(persistence: str) -> int:
    return _HORIZON_DAYS.get(persistence.strip().lower(), _DEFAULT_HORIZON_DAYS)


def _score_directions(tickers: list[dict]) -> tuple[int, int]:
    """Return (supporting, contradicting) count from ticker/revisit-ticker dicts.

    Accepts both ``direction_tag`` (market_tickers) and ``direction``
    (revisit snapshot tickers) so callers don't need to care which key is set.
    """
    sup = con = 0
    for t in tickers or []:
        if not isinstance(t, dict):
            continue
        tag = (t.get("direction") or t.get("direction_tag") or "").lower()
        if tag.startswith("supports"):
            sup += 1
        elif tag.startswith("contradicts"):
            con += 1
    return sup, con


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _trajectory(snap_by_day: dict[int, dict]) -> str:
    """Compare thesis-aligned returns at day-5 vs day-20 snapshots.

    Requires both snapshots to be present.  Returns one of:
      "building" | "stable" | "fading" | "unknown"
    """
    snap5  = snap_by_day.get(5)
    snap20 = snap_by_day.get(20)
    if not snap5 or not snap20:
        return "unknown"

    t5_by_sym  = {
        (t.get("symbol") or "").upper(): t
        for t in (snap5.get("tickers") or [])
        if isinstance(t, dict)
    }
    t20_by_sym = {
        (t.get("symbol") or "").upper(): t
        for t in (snap20.get("tickers") or [])
        if isinstance(t, dict)
    }

    common = set(t5_by_sym) & set(t20_by_sym)
    if not common:
        return "unknown"

    deltas: list[float] = []
    for sym in common:
        t5  = t5_by_sym[sym]
        t20 = t20_by_sym[sym]
        r5  = _safe_float(t5.get("return_5d"))
        r20 = _safe_float(t20.get("return_20d"))
        if r5 is None or r20 is None:
            continue
        role = (t5.get("role") or "beneficiary").lower()
        # Align sign so a positive delta always means "thesis still playing out"
        sign = 1.0 if role == "beneficiary" else -1.0
        deltas.append(sign * r20 - sign * r5)

    if not deltas:
        return "unknown"

    avg_delta = sum(deltas) / len(deltas)
    if avg_delta >= _BUILDING_THRESHOLD_PP:
        return "building"
    if avg_delta <= _FADING_THRESHOLD_PP:
        return "fading"
    return "stable"


# ---------------------------------------------------------------------------
# Thesis-aligned ticker aggregator
# ---------------------------------------------------------------------------

REPRICING_STATES: tuple[str, ...] = (
    "watching",
    "gap_and_hold",
    "grind",
    "retrace",
    "second_leg",
    "fade",
    "invalidation",
    "resolved",
)

_REPRICING_LABELS: dict[str, str] = {
    "watching":      "Watching",
    "gap_and_hold":  "Gap & Hold",
    "grind":         "Grind",
    "retrace":       "Retrace",
    "second_leg":    "Second Leg",
    "fade":          "Fade",
    "invalidation":  "Invalidation",
    "resolved":      "Resolved",
}


def _role_sign(role: str) -> float:
    """Return +1 for beneficiary, -1 for loser.

    Unknown roles default to +1 (treat as beneficiary).  This matches the
    existing direction_tag convention where "supports_thesis" is the
    positive axis.
    """
    return -1.0 if (role or "").strip().lower() == "loser" else 1.0


def _aligned_returns(tickers: list[dict]) -> dict[str, float | None]:
    """Aggregate r1/r5/r20 across tickers, signed to the thesis direction.

    Each ticker's return is multiplied by +1 for beneficiary and -1 for
    loser so a positive aggregate always means "thesis playing out".

    Returns {"r1": mean | None, "r5": ..., "r20": ..., "n": sample count}.
    """
    r1s: list[float] = []
    r5s: list[float] = []
    r20s: list[float] = []
    n = 0
    for t in tickers or []:
        if not isinstance(t, dict):
            continue
        sign = _role_sign(t.get("role", ""))
        r1 = _safe_float(t.get("return_1d"))
        r5 = _safe_float(t.get("return_5d"))
        r20 = _safe_float(t.get("return_20d"))
        if r1 is None and r5 is None and r20 is None:
            continue
        n += 1
        if r1 is not None:
            r1s.append(sign * r1)
        if r5 is not None:
            r5s.append(sign * r5)
        if r20 is not None:
            r20s.append(sign * r20)

    def _mean(xs: list[float]) -> float | None:
        return sum(xs) / len(xs) if xs else None

    return {
        "r1":  _mean(r1s),
        "r5":  _mean(r5s),
        "r20": _mean(r20s),
        "n":   n,
    }


def _best_snapshot_tickers(snap_by_day: dict[int, dict]) -> list[dict]:
    """Return the tickers dict from the latest available revisit snapshot.

    Revisit snapshots carry fresher return_1d / return_5d / return_20d
    than the market_tickers written at save time, so they drive the
    repricing-state classifier when present.
    """
    if not snap_by_day:
        return []
    best = snap_by_day[max(snap_by_day.keys())]
    ts = best.get("tickers")
    return ts if isinstance(ts, list) else []


# ---------------------------------------------------------------------------
# Repricing-state classifier
# ---------------------------------------------------------------------------

def _classify_repricing_state(
    agg: dict[str, float | None],
    age_days: int,
    past_horizon: bool,
) -> tuple[str, str]:
    """Map aggregated thesis-aligned returns to a repricing-state label.

    Returns (state_id, one-line evidence).  Priority order matters — the
    first rule that fires wins, so more severe outcomes (invalidation,
    fade) take precedence over more benign ones (retrace).
    """
    r1  = agg.get("r1")
    r5  = agg.get("r5")
    r20 = agg.get("r20")
    n   = int(agg.get("n") or 0)

    if n == 0 or (r1 is None and r5 is None and r20 is None):
        return "watching", f"No ticker returns yet at {age_days}d — awaiting follow-through."

    # Invalidation: 20d reading clearly against thesis.
    if r20 is not None and r20 <= _INVALIDATION_FLOOR_PP:
        return (
            "invalidation",
            f"20d thesis-aligned return {r20:+.2f}% — thesis invalidated over horizon.",
        )

    # Fade: r5 flipped sign vs r1 (or vs thesis baseline).
    if r5 is not None and r5 < -_REPRICING_NOISE_PP:
        if r1 is not None and r1 > _REPRICING_NOISE_PP:
            return (
                "fade",
                f"Initial {r1:+.2f}% faded to {r5:+.2f}% by 5d — move reversed.",
            )
        # r5 negative AND r1 missing/flat → still a fade (move against thesis early)
        return (
            "fade",
            f"5d thesis-aligned return {r5:+.2f}% — move running against thesis.",
        )

    # Second leg: 20d extends materially past 5d in same direction.
    if (
        r20 is not None and r5 is not None
        and r5 > _REPRICING_NOISE_PP
        and r20 >= r5 * _SECOND_LEG_MULT
    ):
        return (
            "second_leg",
            f"r20 {r20:+.2f}% vs r5 {r5:+.2f}% — follow-through extending past 5d.",
        )

    # Gap & hold: big day-1 move, r5 holds in [0.7, 1.3] band of r1.
    if (
        r1 is not None and r5 is not None
        and r1 >= _GAP_SIGNIFICANCE_PP
        and r1 > 0
    ):
        ratio = r5 / r1
        if _HOLD_BAND_LOW <= ratio <= _HOLD_BAND_HIGH:
            return (
                "gap_and_hold",
                f"r1 {r1:+.2f}% held to r5 {r5:+.2f}% (ratio {ratio:.2f}).",
            )
        # Same-sign but material give-back → retrace.
        if 0 < ratio < _RETRACE_MAX_FRACTION:
            return (
                "retrace",
                f"r1 {r1:+.2f}% faded to r5 {r5:+.2f}% (ratio {ratio:.2f}) — partial retrace.",
            )

    # Grind: small r1, substantial r5 in thesis direction.
    if (
        r5 is not None
        and r5 >= _GRIND_R5_MIN_PP
        and (r1 is None or r1 <= _GRIND_R1_MAX_PP)
    ):
        r1_txt = f"{r1:+.2f}%" if r1 is not None else "n/a"
        return (
            "grind",
            f"r5 {r5:+.2f}% built from a small r1 ({r1_txt}) — slow accumulation.",
        )

    # Past horizon with nothing else distinctive fires → resolved.
    if past_horizon:
        return (
            "resolved",
            f"Past horizon; r5 {r5 if r5 is not None else 'n/a'}, r20 {r20 if r20 is not None else 'n/a'}.",
        )

    # Too young / inconclusive.
    if age_days < _WATCHING_AGE_DAYS:
        return "watching", f"{age_days}d since event — early read, awaiting r5/r20."

    # Default: watching with partial read.
    rbits = []
    if r1  is not None: rbits.append(f"r1 {r1:+.2f}%")
    if r5  is not None: rbits.append(f"r5 {r5:+.2f}%")
    if r20 is not None: rbits.append(f"r20 {r20:+.2f}%")
    return "watching", f"No dominant pattern yet ({', '.join(rbits)})."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_persistence_signal(
    event: dict,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Classify whether an event's effects are still playing out.

    Parameters
    ----------
    event:
        Fully decoded event dict (revisit_snapshots and market_tickers decoded).
    now:
        Override current time (for testing).

    Returns
    -------
    {
        "status":       "watching" | "active" | "fading" | "resolved",
        "label":        str,   # short UI label
        "evidence":     str,   # one-line explanation
        "horizon_days": int,   # expected effect duration
        "days_elapsed": int,   # event age in days
    }
    """
    now_dt = now or datetime.now()
    persistence  = (event.get("persistence") or "").strip().lower()
    horizon_days = _horizon_for(persistence)
    age_days     = event_age_policy.event_age_days(event, now_dt)

    snapshots = event.get("revisit_snapshots") or []
    tickers   = event.get("market_tickers") or []

    snap_by_day: dict[int, dict] = {}
    for s in snapshots:
        if isinstance(s, dict):
            day = s.get("day")
            if isinstance(day, int):
                snap_by_day[day] = s

    best_day  = max(snap_by_day.keys(), default=None)
    best_snap = snap_by_day[best_day] if best_day is not None else None

    past_horizon  = age_days > horizon_days
    days_remaining = max(0, horizon_days - age_days)

    # ------------------------------------------------------------------
    # Repricing-state classification (additive; runs regardless of legacy branches).
    # Prefer revisit-snapshot tickers (fresher returns) over market_tickers.
    # ------------------------------------------------------------------
    revisit_tickers = _best_snapshot_tickers(snap_by_day)
    source_tickers  = revisit_tickers if revisit_tickers else tickers
    aligned = _aligned_returns(source_tickers)
    repricing_state, repricing_evidence = _classify_repricing_state(
        aligned, age_days, past_horizon,
    )
    repricing_block = {
        "state":           repricing_state,
        "label":           _REPRICING_LABELS[repricing_state],
        "evidence":        repricing_evidence,
        "source":          "revisit" if revisit_tickers else "initial",
        "metrics": {
            "thesis_aligned_r1":  round(aligned["r1"],  3) if aligned["r1"]  is not None else None,
            "thesis_aligned_r5":  round(aligned["r5"],  3) if aligned["r5"]  is not None else None,
            "thesis_aligned_r20": round(aligned["r20"], 3) if aligned["r20"] is not None else None,
            "n_tickers":          aligned["n"],
        },
    }

    def _result(status: str, label: str, evidence: str) -> dict[str, Any]:
        """Build the legacy-compatible dict with the additive repricing block."""
        return {
            "status":         status,
            "label":          label,
            "evidence":       evidence,
            "horizon_days":   horizon_days,
            "days_elapsed":   age_days,
            "repricing":      repricing_block,
            "repricing_state":    repricing_block["state"],
            "repricing_label":    repricing_block["label"],
            "repricing_evidence": repricing_block["evidence"],
        }

    # ------------------------------------------------------------------
    # Case 1: past expected horizon
    # ------------------------------------------------------------------
    if past_horizon:
        if best_snap:
            sup, con = _score_directions(best_snap.get("tickers") or [])
            total = sup + con
            if total > 0 and con > sup:
                return _result(
                    "resolved", "Contradicted",
                    f"Beyond {horizon_days}d {persistence} horizon; "
                    f"thesis contradicted ({con}/{total} tickers, day-{best_day} revisit)",
                )
        source = f"day-{best_day} revisit" if best_snap else "no revisit data"
        return _result(
            "resolved", "Resolved",
            f"Beyond {horizon_days}d {persistence} horizon ({source})",
        )

    # ------------------------------------------------------------------
    # Case 2: within horizon — no revisit, event too young
    # ------------------------------------------------------------------
    if not best_snap and age_days < _WATCHING_AGE_DAYS:
        return _result(
            "watching", "Watching",
            f"{age_days}d since event — awaiting follow-through",
        )

    # ------------------------------------------------------------------
    # Case 3: direction evidence (revisit or initial market check)
    # ------------------------------------------------------------------
    if best_snap:
        sup, con = _score_directions(best_snap.get("tickers") or [])
        total = sup + con
        source = f"day-{best_day} revisit"
    else:
        sup, con = _score_directions(tickers)
        total = sup + con
        source = "initial check"

    traj = _trajectory(snap_by_day)

    if total == 0:
        return _result(
            "watching", "Unvalidated",
            f"No direction data at {age_days}d — revisit recommended "
            f"({days_remaining}d left in {persistence} horizon)",
        )

    support_ratio = sup / total

    # Active (majority supporting)
    if support_ratio >= _SUPPORT_HIGH:
        if traj == "building":
            return _result(
                "active", "Active \u2191",
                f"Building momentum; {sup}/{total} supporting "
                f"({source}); {days_remaining}d left",
            )
        if traj == "fading":
            return _result(
                "fading", "Fading",
                f"Returns declining; {sup}/{total} still supporting ({source})",
            )
        return _result(
            "active", "Active",
            f"{sup}/{total} tickers supporting thesis "
            f"({source}); {days_remaining}d left",
        )

    # Contradicted (minority supporting)
    if support_ratio <= _SUPPORT_LOW:
        return _result(
            "fading", "Fading",
            f"Weak support: {sup}/{total} tickers supporting ({source})",
        )

    # Mixed
    return _result(
        "fading", "Mixed",
        f"Split signals: {sup}/{total} supporting "
        f"({source}); {days_remaining}d left",
    )
