"""
thesis_scorecard.py

Horizon-aware thesis scorecard.

Why this module
---------------
The pipeline already produces:

  * ``horizon_checkpoints`` — the LLM-written ``expected`` / ``confirms_if``
    / ``falsifies_if`` criteria at 1d / 5d / 20d.
  * ``market_tickers`` — initial return reads with return_1d / return_5d /
    return_20d + role + direction_tag.
  * ``revisit_snapshots`` — optional follow-through captures taken at the
    same 1d / 5d / 20d anchors when the event has aged enough.

None of those three tell a reader whether the THESIS is on track —
they tell you the text of expectation and the tape separately.  This
module joins the two into one compact scorecard::

    per horizon → status {confirmed | mixed | failed | pending}
    aggregate   → status {on_track  | drifting | breaking | pending}

Per-horizon status is derived purely from realized return direction
vs ticker role: beneficiaries with positive returns SUPPORT; losers
with negative returns SUPPORT; everything else is either flat (noise
band) or contradicting.  The LLM-written criteria are forwarded into
the scorecard as context text — the reader sees BOTH what was
expected and what actually happened at each horizon.

Pure composer.  No I/O.  Never raises.
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Noise bands per horizon — returns inside these count as "flat", not
# direction evidence.  Tuned to roughly match the magnitude that most
# cross-sectional beta-driven noise produces at each tenor.
# ---------------------------------------------------------------------------

_NOISE_BAND: dict[str, float] = {
    "1d":  0.3,   # intraday noise band
    "5d":  0.8,   # mid-week drift band
    "20d": 2.0,   # month-scale noise
}


# Minimum support:contradict ratio needed to call the horizon "confirmed"
# or "failed".  Below this the horizon is "mixed".  Two-to-one is a
# reasonable institutional threshold — fewer false positives than 1.5x,
# fewer misses than 3x.
_RATIO_GATE: float = 2.0


# Supported horizon order.  Everything outside this tuple is ignored.
_HORIZONS: tuple[str, ...] = ("1d", "5d", "20d")


# ---------------------------------------------------------------------------
# Ticker → per-horizon verdict
# ---------------------------------------------------------------------------

def _role_sign(role: Any) -> Optional[int]:
    """Return +1 for beneficiary, -1 for loser, None otherwise.

    The sign is the thesis-consistent direction: a beneficiary with
    return sign +1 supports; a loser with return sign -1 supports.
    """
    if not isinstance(role, str):
        return None
    r = role.strip().lower()
    if r == "beneficiary":
        return +1
    if r == "loser":
        return -1
    return None


def _classify_ticker_at_horizon(
    ticker: dict, horizon: str,
) -> Optional[str]:
    """Return ``"support" | "contradict" | "flat" | "pending"`` or None
    when the ticker is unusable (bad role, no return field)."""
    ret = ticker.get(f"return_{horizon}")
    if ret is None:
        return "pending"
    sign = _role_sign(ticker.get("role"))
    if sign is None:
        return None
    try:
        val = float(ret)
    except (TypeError, ValueError):
        return None

    band = _NOISE_BAND.get(horizon, 0.0)
    if abs(val) < band:
        return "flat"
    thesis_direction = (sign * val) > 0
    return "support" if thesis_direction else "contradict"


# ---------------------------------------------------------------------------
# Snapshot preference helper — prefer the revisit snapshot for the
# horizon when one exists, otherwise fall back to the initial tickers.
# ---------------------------------------------------------------------------

def _tickers_for_horizon(
    horizon: str,
    market_tickers: list[dict],
    revisit_snapshots: Optional[list[dict]],
) -> list[dict]:
    """Return the ticker list carrying return_{horizon} for this horizon.

    Revisit snapshots are keyed by ``day`` (1, 5, 20); when a snapshot
    for this horizon exists its ``tickers`` list is authoritative for
    that horizon's status — it's the post-hoc measurement.  Otherwise
    fall back to the initial ``market_tickers`` which carry rolling
    returns computed at analysis time.
    """
    if revisit_snapshots:
        day = {"1d": 1, "5d": 5, "20d": 20}.get(horizon)
        for snap in revisit_snapshots:
            if isinstance(snap, dict) and snap.get("day") == day:
                tickers = snap.get("tickers") or []
                if isinstance(tickers, list) and tickers:
                    return tickers
    return market_tickers or []


# ---------------------------------------------------------------------------
# Per-horizon composer
# ---------------------------------------------------------------------------

def _score_horizon(
    horizon: str,
    expected_block: dict,
    market_tickers: list[dict],
    revisit_snapshots: Optional[list[dict]],
) -> dict[str, Any]:
    """Score a single horizon.  Returns the documented per-horizon dict."""
    tickers = _tickers_for_horizon(horizon, market_tickers, revisit_snapshots)

    supporting:    list[dict] = []
    contradicting: list[dict] = []
    flat:          list[dict] = []
    pending:       list[dict] = []

    for t in tickers:
        if not isinstance(t, dict):
            continue
        verdict = _classify_ticker_at_horizon(t, horizon)
        if verdict is None:
            continue
        entry = {
            "symbol":  t.get("symbol", ""),
            "role":    t.get("role", ""),
            "return":  t.get(f"return_{horizon}"),
        }
        if verdict == "support":
            supporting.append(entry)
        elif verdict == "contradict":
            contradicting.append(entry)
        elif verdict == "flat":
            flat.append(entry)
        else:
            pending.append(entry)

    resolved = len(supporting) + len(contradicting) + len(flat)
    total = resolved + len(pending)

    # Status classification.
    if total == 0 or resolved == 0:
        status = "pending"
        rationale = (
            f"No {horizon} returns available yet — all tickers pending."
            if total > 0 else
            f"No tickers usable at {horizon}."
        )
    elif len(supporting) >= _RATIO_GATE * max(len(contradicting), 1) and len(supporting) > 0:
        status = "confirmed"
        rationale = (
            f"{len(supporting)}/{resolved} tickers moved with the thesis "
            f"at {horizon}; "
            f"{len(contradicting)} contradict, {len(flat)} flat"
        )
    elif len(contradicting) >= _RATIO_GATE * max(len(supporting), 1) and len(contradicting) > 0:
        status = "failed"
        rationale = (
            f"{len(contradicting)}/{resolved} tickers moved AGAINST the thesis "
            f"at {horizon}; "
            f"{len(supporting)} support, {len(flat)} flat"
        )
    else:
        status = "mixed"
        rationale = (
            f"Split at {horizon}: {len(supporting)} support / "
            f"{len(contradicting)} contradict / {len(flat)} flat"
        )

    return {
        "horizon":                horizon,
        "status":                 status,
        "expected_criteria":      list(expected_block.get("expected") or []),
        "confirmation_criteria":  list(expected_block.get("confirms_if") or []),
        "falsification_criteria": list(expected_block.get("falsifies_if") or []),
        "realized": {
            "supporting":     supporting,
            "contradicting":  contradicting,
            "flat":           flat,
            "pending":        pending,
        },
        "rationale": rationale,
    }


# ---------------------------------------------------------------------------
# Aggregate composer
# ---------------------------------------------------------------------------

def _aggregate(per_horizon: list[dict]) -> dict[str, Any]:
    """Classify the overall thesis status from per-horizon verdicts.

    Rules:
      * every horizon pending                       → ``"pending"``
      * any failure at 5d or 20d                    → ``"breaking"``
      * all resolved horizons confirmed             → ``"on_track"``
      * otherwise                                   → ``"drifting"``

    A 1d "failed" alone is treated as drifting — first-day noise and
    positioning dynamics can contradict the thesis without the mechanism
    being wrong.  A 5d or 20d failure is structural and lights the
    breaking beacon.
    """
    resolved = [h for h in per_horizon if h["status"] != "pending"]
    if not resolved:
        return {
            "status":             "pending",
            "resolved_horizons":  0,
            "pending_horizons":   len(per_horizon),
            "rationale":
                "Scorecard is pending — no horizons have enough return data yet.",
        }

    fails_structural = [
        h["horizon"] for h in per_horizon
        if h["status"] == "failed" and h["horizon"] in ("5d", "20d")
    ]
    if fails_structural:
        return {
            "status":             "breaking",
            "resolved_horizons":  len(resolved),
            "pending_horizons":   len(per_horizon) - len(resolved),
            "rationale":
                f"Thesis is breaking — failure(s) at {', '.join(fails_structural)}",
        }

    if all(h["status"] == "confirmed" for h in resolved):
        return {
            "status":             "on_track",
            "resolved_horizons":  len(resolved),
            "pending_horizons":   len(per_horizon) - len(resolved),
            "rationale":
                f"Thesis on track — {len(resolved)} horizon(s) confirmed, "
                "no failures",
        }

    # Any mix of confirmed / mixed / 1d-failed lands here.
    confirmed_horizons = [h["horizon"] for h in resolved if h["status"] == "confirmed"]
    mixed_horizons     = [h["horizon"] for h in resolved if h["status"] == "mixed"]
    short_fails        = [h["horizon"] for h in resolved if h["status"] == "failed"]

    bits: list[str] = []
    if confirmed_horizons:
        bits.append(f"{len(confirmed_horizons)} confirmed ({', '.join(confirmed_horizons)})")
    if mixed_horizons:
        bits.append(f"{len(mixed_horizons)} mixed ({', '.join(mixed_horizons)})")
    if short_fails:
        bits.append(f"{len(short_fails)} short-term failure ({', '.join(short_fails)})")

    return {
        "status":             "drifting",
        "resolved_horizons":  len(resolved),
        "pending_horizons":   len(per_horizon) - len(resolved),
        "rationale":          "Thesis drifting — " + "; ".join(bits),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def compute_thesis_scorecard(
    horizon_checkpoints: Optional[dict],
    market_tickers: Optional[list[dict]],
    revisit_snapshots: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """Build the horizon-aware thesis scorecard.

    Returned shape::

        {
          "available":      bool,
          "timing_profile": str,                 # echo from horizon_checkpoints
          "per_horizon":    [ ... 3 items ... ], # always 1d / 5d / 20d
          "aggregate":      {
            "status":             "on_track" | "drifting" | "breaking" | "pending",
            "resolved_horizons":  int,
            "pending_horizons":   int,
            "rationale":          str,
          },
        }

    When ``horizon_checkpoints`` is empty / malformed the scorecard still
    returns a well-formed structure with ``available=False`` so callers
    can always dereference the shape safely.
    """
    hc = horizon_checkpoints if isinstance(horizon_checkpoints, dict) else {}
    timing_profile = hc.get("timing_profile", "unknown")
    raw_horizons = hc.get("horizons") if isinstance(hc.get("horizons"), list) else []

    # Index the LLM-written criteria by horizon name so the composer
    # always emits 1d / 5d / 20d in a fixed order, even if the LLM
    # skipped one.
    criteria_by_horizon: dict[str, dict] = {}
    for entry in raw_horizons:
        if not isinstance(entry, dict):
            continue
        name = entry.get("horizon")
        if isinstance(name, str) and name in _HORIZONS:
            criteria_by_horizon[name] = entry

    tickers = market_tickers if isinstance(market_tickers, list) else []
    snaps   = revisit_snapshots if isinstance(revisit_snapshots, list) else None

    per_horizon = [
        _score_horizon(h, criteria_by_horizon.get(h, {}), tickers, snaps)
        for h in _HORIZONS
    ]
    aggregate = _aggregate(per_horizon)

    return {
        "available":      bool(criteria_by_horizon) or bool(tickers) or bool(snaps),
        "timing_profile": timing_profile,
        "per_horizon":    per_horizon,
        "aggregate":      aggregate,
    }
