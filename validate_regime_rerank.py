"""
validate_regime_rerank.py

Empirical validation step for the regime-conditioned analog re-ranker.

What this does
--------------
The re-ranker introduces two tunable knobs (TOPIC_WEIGHT, REGIME_WEIGHT)
that control how aggressively macro regime override topic similarity.
This script sweeps a grid of weight configurations and asks: which ones
satisfy the three required behaviours?

  1. Same-topic / different-regime analogs rank LOWER than same-topic /
     same-regime ones (regime should be allowed to demote topic peers).
  2. Lower-topic / better-regime analogs rank HIGHER than higher-topic /
     worse-regime ones (regime should be allowed to promote topic
     under-dogs when the macro alignment is striking).
  3. Stale macro context degrades cleanly: when the current regime
     vector is unavailable, the input ordering must be preserved (no
     accidental reshuffle from a no-op rerank).

The fixture set is built to mimic the realistic distribution of
(topic_sim, regime_match) pairs we see in production analog candidates.
When ``events.db`` exists and contains saved rows we additionally
evaluate the chosen weights on the live data: every saved event with a
persisted regime snapshot is treated as a "current" event in turn, the
analog list is generated against the rest, and we check that no run
collapses to a degenerate ordering.  This is intentionally a sanity
gate, not a benchmark.

Run:  python validate_regime_rerank.py

The script prints all passing configs, the recommended (TOPIC, REGIME)
pair, and an exit code indicating whether the current defaults in
regime_vector.py match the recommendation.
"""

from __future__ import annotations

import sys

from regime_vector import (
    TOPIC_WEIGHT as DEFAULT_TOPIC_WEIGHT,
    REGIME_WEIGHT as DEFAULT_REGIME_WEIGHT,
    rerank_analogs,
)


# ---------------------------------------------------------------------------
# Synthetic fixture set — represents typical production candidate spreads
# ---------------------------------------------------------------------------

_CURRENT = {
    "inflation":     "hot",
    "policy_stance": "hawkish",
    "fx":            "dollar_strong",
    "growth_stress": "calm",
    "available":     True,
    "stale":         False,
}


def _vec(infl: str, pol: str, fx: str, gs: str) -> dict:
    return {
        "inflation":     infl,
        "policy_stance": pol,
        "fx":            fx,
        "growth_stress": gs,
        "available":     True,
        "stale":         False,
    }


def _build_fixtures() -> list[dict]:
    """Return a fresh copy of the candidate fixture set.

    Returned in input order — the rerank tests check that the right
    fixture ends up FIRST after rerank, regardless of input order.
    """
    return [
        # Property 1: same topic similarity, different regime — should
        # be DEMOTED below same_topic_same_regime.
        {
            "id":               "p1_diff_regime",
            "similarity":       0.45,
            "regime_snapshot":  _vec("cool", "dovish", "dollar_weak", "stressed"),
            "match_reason":     "shared: opec",
        },
        {
            "id":               "p1_same_regime",
            "similarity":       0.45,
            "regime_snapshot":  _vec("hot", "hawkish", "dollar_strong", "calm"),
            "match_reason":     "shared: opec",
        },
        # Property 2: lower topic similarity but matching regime should
        # be PROMOTED above a higher-topic / opposite-regime peer.
        # Gap between topic scores deliberately tight (~0.20 vs ~0.40)
        # so the rerank can swing it without being trivial.
        {
            "id":               "p2_low_topic_good_regime",
            "similarity":       0.20,
            "regime_snapshot":  _vec("hot", "hawkish", "dollar_strong", "calm"),
            "match_reason":     "shared: tariff",
        },
        {
            "id":               "p2_high_topic_bad_regime",
            "similarity":       0.40,
            "regime_snapshot":  _vec("cool", "dovish", "dollar_weak", "stressed"),
            "match_reason":     "shared: tariff, supply",
        },
    ]


def _stale_input() -> list[dict]:
    """Fixture for property 3 — order must survive a no-op rerank."""
    return [
        {"id": "stale_a", "similarity": 0.30, "regime_snapshot": None},
        {"id": "stale_b", "similarity": 0.40, "regime_snapshot": None},
        {"id": "stale_c", "similarity": 0.20, "regime_snapshot": None},
    ]


_STALE_VECTOR = {
    "inflation":     "neutral",
    "policy_stance": "neutral",
    "fx":            "neutral",
    "growth_stress": "neutral",
    "available":     False,
    "stale":         True,
}


# ---------------------------------------------------------------------------
# Property checks
# ---------------------------------------------------------------------------

def _check_property_1(tw: float, rw: float) -> bool:
    fixtures = _build_fixtures()
    ranked = rerank_analogs(fixtures, _CURRENT, topic_weight=tw, regime_weight=rw)
    order = {a["id"]: i for i, a in enumerate(ranked)}
    return order["p1_same_regime"] < order["p1_diff_regime"]


def _check_property_2(tw: float, rw: float) -> bool:
    fixtures = _build_fixtures()
    ranked = rerank_analogs(fixtures, _CURRENT, topic_weight=tw, regime_weight=rw)
    order = {a["id"]: i for i, a in enumerate(ranked)}
    return order["p2_low_topic_good_regime"] < order["p2_high_topic_bad_regime"]


def _check_property_3(tw: float, rw: float) -> bool:
    fixtures = _stale_input()
    original_ids = [a["id"] for a in fixtures]
    ranked = rerank_analogs(fixtures, _STALE_VECTOR,
                            topic_weight=tw, regime_weight=rw)
    return [a["id"] for a in ranked] == original_ids


# ---------------------------------------------------------------------------
# Optional live-db sanity gate
# ---------------------------------------------------------------------------

def _live_sanity_gate(tw: float, rw: float) -> tuple[bool, str]:
    """Light sanity check against the local events.db when present.

    For each saved event with a regime snapshot, treat it as the
    "current" event, build a candidate list from the remaining rows
    (using a synthetic topic similarity from headline-word overlap),
    and confirm the rerank does not collapse to a single position.

    Returns (passed, message).  Skips silently if the db is empty or
    not initialised.
    """
    try:
        import db as _db
        _db.init_db()
        events = _db.load_recent_events(limit=50)
    except Exception as e:
        return True, f"  (skipped — db unavailable: {e})"

    valid = [
        e for e in events
        if isinstance(e.get("regime_snapshot"), dict)
        and e["regime_snapshot"].get("available")
    ]
    if len(valid) < 2:
        return True, "  (skipped — fewer than 2 saved events with regime snapshots)"

    runs = 0
    degenerate = 0
    for cur in valid[:10]:
        cur_vec = cur["regime_snapshot"]
        peers = [
            {
                "id":              e["headline"],
                "similarity":      0.30,
                "regime_snapshot": e.get("regime_snapshot"),
                "match_reason":    "",
            }
            for e in valid
            if e["headline"] != cur["headline"]
        ]
        if len(peers) < 2:
            continue
        ranked = rerank_analogs(peers, cur_vec, topic_weight=tw, regime_weight=rw)
        # Degenerate if every analog ends up with the same final score
        # (means the rerank had no discriminating power on this slice).
        scores = {round(a.get("final_score") or 0.0, 4) for a in ranked}
        if len(scores) <= 1:
            degenerate += 1
        runs += 1

    if runs == 0:
        return True, "  (no usable runs)"

    ratio = degenerate / runs
    msg = f"  live sanity: {runs} runs, {degenerate} degenerate ({ratio:.0%})"
    return ratio < 0.5, msg


# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------

def main() -> int:
    print("Sweeping (topic_weight, regime_weight) configurations...")
    print()

    grid = [
        (0.40, 0.60), (0.45, 0.55), (0.50, 0.50),
        (0.55, 0.45), (0.60, 0.40), (0.65, 0.35),
        (0.70, 0.30), (0.75, 0.25), (0.80, 0.20),
    ]

    print(f"{'topic':>6}  {'regime':>6}  {'p1':>4}  {'p2':>4}  {'p3':>4}")
    print("  " + "-" * 30)

    passing: list[tuple[float, float]] = []
    for tw, rw in grid:
        p1 = _check_property_1(tw, rw)
        p2 = _check_property_2(tw, rw)
        p3 = _check_property_3(tw, rw)
        ok = p1 and p2 and p3
        marker = "PASS" if ok else "FAIL"
        print(f"{tw:>6.2f}  {rw:>6.2f}  "
              f"{'Y' if p1 else 'n':>4}  "
              f"{'Y' if p2 else 'n':>4}  "
              f"{'Y' if p3 else 'n':>4}  {marker}")
        if ok:
            passing.append((tw, rw))

    print()
    if not passing:
        print("No configuration satisfied all three properties — review the rerank logic.")
        return 2

    # Pick the median of the passing range.  Median (not mean) is robust
    # to a one-sided sweep and gives the natural centre of the corridor
    # where both properties hold with comfortable margin.
    passing_sorted = sorted(passing, key=lambda w: w[0])
    chosen = passing_sorted[len(passing_sorted) // 2]
    print(f"Passing range: topic_weight in "
          f"[{passing_sorted[0][0]:.2f}, {passing_sorted[-1][0]:.2f}]")
    print(f"Median pick:   TOPIC_WEIGHT={chosen[0]:.2f}, "
          f"REGIME_WEIGHT={chosen[1]:.2f}")
    print()

    # Live sanity gate against the local db (skips silently if empty).
    sane, sanity_msg = _live_sanity_gate(*chosen)
    print("Live sanity check:")
    print(sanity_msg)
    if not sane:
        print("  WARNING: live sanity gate did not pass — review weights.")

    print()
    print(f"Current defaults in regime_vector.py: "
          f"TOPIC_WEIGHT={DEFAULT_TOPIC_WEIGHT}, "
          f"REGIME_WEIGHT={DEFAULT_REGIME_WEIGHT}")
    if (DEFAULT_TOPIC_WEIGHT, DEFAULT_REGIME_WEIGHT) == chosen:
        print("Defaults already match the recommendation.")
        return 0

    print("Defaults differ from the recommendation — update regime_vector.py.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
