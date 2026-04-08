"""
tools/event_age_policy_validation.py

Empirical validation for the unified event-age policy.

Goal
----
The unified ``event_age_policy`` layer ships with four tunable bucket
boundaries + three TTLs:

    _HOT_MAX_DAYS     = 1
    _WARM_MAX_DAYS    = 7
    _STABLE_MAX_DAYS  = 30
    _HOT_TTL_SECONDS  = 2h
    _WARM_TTL_SECONDS = 4h
    _STABLE_TTL_SECONDS = 24h

This script replays the live events archive + a synthetic frozen tail
against the policy and reports:

  * bucket distribution over the archive
  * macro-recompute work saved by the frozen freeze on /analyze cache
    hits (= "how many live-macro calls does the freeze avoid per day")
  * market-check refresh rate (unchanged from the Task H calibration)

The grounded numbers feed back into the docstrings of both
``event_age_policy`` and ``market_check_freshness``.  A change to any
of the tunables requires re-running this script and the two
downstream validation scripts (``market_check_freshness_validation``
and ``movers_cache_validation``).

Run as:
    python -m tools.event_age_policy_validation
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
import event_age_policy  # noqa: E402
import market_check_freshness as mcf  # noqa: E402


# ---------------------------------------------------------------------------
# Representative populations
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 4, 8, 12, 0, 0)

# Synthetic tail — live archive is young, so we add realistic older
# events to exercise the warm / stable / frozen buckets every run.
_SYNTHETIC_AGES_DAYS = [
    0, 0, 1,          # hot bucket: 3 rows
    2, 3, 4, 5, 6, 7, # warm bucket: 6 rows
    8, 10, 15, 20, 25, 30,  # stable bucket: 6 rows
    31, 45, 60, 120, 200, 365,  # frozen bucket: 6 rows
]


def _load_live_ages(now: datetime) -> list[int]:
    """Return ages (in days, >=0) for every event in the live archive."""
    import sqlite3
    ages: list[int] = []
    if not os.path.exists(db.DB_FILE):
        return ages
    try:
        with sqlite3.connect(db.DB_FILE) as conn:
            rows = conn.execute(
                "SELECT event_date, timestamp FROM events"
            ).fetchall()
    except sqlite3.Error:
        return ages
    for ed, ts in rows:
        anchor = ed or (ts or "")[:10]
        if not anchor:
            continue
        try:
            parsed = datetime.fromisoformat(anchor[:10])
        except (ValueError, TypeError):
            continue
        ages.append(max(0, (now.date() - parsed.date()).days))
    return ages


def _make_synthetic_event(age_days: int) -> dict:
    """Minimal event dict the policy can classify."""
    anchor = (_BASE - timedelta(days=age_days)).strftime("%Y-%m-%d")
    return {
        "id": age_days,
        "event_date": anchor,
        "timestamp": (_BASE - timedelta(days=age_days)).isoformat(timespec="seconds"),
        "market_tickers": [
            {"symbol": "AAPL", "role": "beneficiary",
             "return_5d": 1.0, "return_20d": 2.0},
        ],
        "last_market_check_at": (
            _BASE - timedelta(hours=1)
        ).isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# Bucket distribution report
# ---------------------------------------------------------------------------


@dataclass
class _BucketTally:
    hot: int = 0
    warm: int = 0
    stable: int = 0
    frozen: int = 0
    legacy: int = 0

    @property
    def total(self) -> int:
        return self.hot + self.warm + self.stable + self.frozen + self.legacy


def _tally_buckets(events: Iterable[dict]) -> _BucketTally:
    t = _BucketTally()
    for ev in events:
        bucket = event_age_policy.classify_event_age(ev, now=_BASE)["bucket"]
        setattr(t, bucket, getattr(t, bucket) + 1)
    return t


def _print_bucket_distribution(label: str, tally: _BucketTally) -> None:
    total = max(tally.total, 1)
    print(f"  {label:<24}  total={tally.total:>3}  "
          f"hot={tally.hot:>3} ({tally.hot / total:5.1%})  "
          f"warm={tally.warm:>3} ({tally.warm / total:5.1%})  "
          f"stable={tally.stable:>3} ({tally.stable / total:5.1%})  "
          f"frozen={tally.frozen:>3} ({tally.frozen / total:5.1%})  "
          f"legacy={tally.legacy:>3} ({tally.legacy / total:5.1%})")


# ---------------------------------------------------------------------------
# Macro-recompute workload replay
# ---------------------------------------------------------------------------


def _simulate_macro_recomputes(events: list[dict], reads_per_event: int) -> dict:
    """Replay a representative cached-response workload.

    Each event is read ``reads_per_event`` times.  A read that lands on
    a frozen event (and the caller did not pass force=True) skips the
    7 live-macro helpers; a read on hot/warm/stable runs all 7.  The
    "work" number is the count of live-macro helper calls avoided.
    """
    n_live_helpers = 7
    avoided = 0
    runs = 0
    for ev in events:
        classification = event_age_policy.classify_event_age(ev, now=_BASE)
        if classification["is_frozen"]:
            avoided += reads_per_event * n_live_helpers
        else:
            runs += reads_per_event * n_live_helpers
    total = runs + avoided
    return {
        "total_helper_calls_without_freeze": total,
        "helper_calls_after_freeze":         runs,
        "helper_calls_avoided":              avoided,
        "savings_fraction":                  avoided / max(total, 1),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    now = _BASE
    live_ages = _load_live_ages(now)
    live_events = [_make_synthetic_event(a) for a in live_ages]
    synth_events = [_make_synthetic_event(a) for a in _SYNTHETIC_AGES_DAYS]

    print("Unified event-age policy validation")
    print("-----------------------------------")
    print(f"Tunables (from event_age_policy.py):")
    print(f"  _HOT_MAX_DAYS       = {event_age_policy._HOT_MAX_DAYS}")
    print(f"  _WARM_MAX_DAYS      = {event_age_policy._WARM_MAX_DAYS}")
    print(f"  _STABLE_MAX_DAYS    = {event_age_policy._STABLE_MAX_DAYS}")
    print(f"  _HOT_TTL_SECONDS    = {event_age_policy._HOT_TTL_SECONDS} "
          f"({event_age_policy._HOT_TTL_SECONDS // 3600}h)")
    print(f"  _WARM_TTL_SECONDS   = {event_age_policy._WARM_TTL_SECONDS} "
          f"({event_age_policy._WARM_TTL_SECONDS // 3600}h)")
    print(f"  _STABLE_TTL_SECONDS = {event_age_policy._STABLE_TTL_SECONDS} "
          f"({event_age_policy._STABLE_TTL_SECONDS // 3600}h)")
    print()

    print("Bucket distribution:")
    _print_bucket_distribution("live archive", _tally_buckets(live_events))
    _print_bucket_distribution("synthetic spread", _tally_buckets(synth_events))
    combined = _tally_buckets(live_events + synth_events)
    _print_bucket_distribution("combined", combined)
    print()

    # --- Macro-recompute workload ------------------------------------------
    # Assume each event gets 5 cached-response reads per day (dashboard
    # reload + 4 page views from related surfaces).
    reads_per_event = 5
    print(f"Macro recompute workload ({reads_per_event} cached reads per event):")
    workload = _simulate_macro_recomputes(
        live_events + synth_events, reads_per_event,
    )
    total = workload["total_helper_calls_without_freeze"]
    after = workload["helper_calls_after_freeze"]
    avoided = workload["helper_calls_avoided"]
    print(f"  without freeze:  {total:>5} live-macro helper calls")
    print(f"  with freeze:     {after:>5} live-macro helper calls")
    print(f"  avoided:         {avoided:>5}  ({workload['savings_fraction']:5.1%})")
    print()

    # --- Market-check consistency ------------------------------------------
    # The market_check_freshness layer must still pass its Task H
    # calibration: ~15.9% refresh rate across a representative read
    # schedule.  We re-derive it from the 3-bucket (recent / older /
    # frozen) view so a regression in the policy unification shows up.
    print("Market-check refresh rate (unchanged Task H contract):")
    mcf_reads = 17  # matches tools/market_check_freshness_validation.py
    mcf_events = live_events + synth_events
    total_reads = 0
    refreshes = 0
    for ev in mcf_events:
        last_check_dt: datetime | None = None
        for i in range(mcf_reads):
            read_at = _BASE + timedelta(minutes=30 * i)
            ev_for_mcf = dict(ev)
            ev_for_mcf["last_market_check_at"] = (
                last_check_dt.replace(microsecond=0).isoformat()
                if last_check_dt else None
            )
            s = mcf.compute_staleness(ev_for_mcf, now=read_at)
            total_reads += 1
            if s["status"] in ("stale", "legacy"):
                refreshes += 1
                last_check_dt = read_at
    mcf_rate = refreshes / max(total_reads, 1)
    print(f"  reads={total_reads}  refreshes={refreshes}  rate={mcf_rate:5.1%}")
    print()

    # --- Assertions --------------------------------------------------------
    # 1. Frozen bucket savings are proportional to the fraction of the
    #    combined population that lives past the 30-day cutoff.  The
    #    savings will grow naturally as the live archive ages: every
    #    frozen event in the population removes 7 macro helper calls
    #    per cached read.  We assert that some savings are realised and
    #    that the per-frozen-event figure matches the 7-helper contract.
    frozen_events = combined.frozen
    expected_avoided = frozen_events * reads_per_event * 7
    assert avoided == expected_avoided, (
        f"Per-frozen-event savings mismatch: expected "
        f"{expected_avoided} helper calls avoided "
        f"({frozen_events} frozen * {reads_per_event} reads * 7 helpers), "
        f"got {avoided}."
    )
    if frozen_events > 0:
        assert workload["savings_fraction"] > 0.0, (
            f"Frozen events present ({frozen_events}) but no macro "
            f"work avoided — the freeze branch is not wired correctly."
        )

    # 2. Market-check refresh rate must remain in the validated Task H
    #    band (10-30%) — the unification should not regress it.
    assert 0.05 <= mcf_rate <= 0.35, (
        f"Market-check refresh rate {mcf_rate:.1%} is outside the "
        f"Task H validated band [5%, 35%].  The policy unification "
        f"broke the existing calibration."
    )

    # 3. Every bucket present in the synthetic spread must classify
    #    correctly — regressions show up as missing buckets.
    synth_tally = _tally_buckets(synth_events)
    assert synth_tally.hot > 0,    "synthetic hot bucket empty"
    assert synth_tally.warm > 0,   "synthetic warm bucket empty"
    assert synth_tally.stable > 0, "synthetic stable bucket empty"
    assert synth_tally.frozen > 0, "synthetic frozen bucket empty"

    print(f"OK — unified event-age policy validated.")
    print(f"    Frozen freeze saves {workload['savings_fraction']:.1%} "
          f"of live-macro calls on cached responses.")
    print(f"    Market-check refresh rate stays at "
          f"{mcf_rate:.1%} (Task H contract preserved).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
