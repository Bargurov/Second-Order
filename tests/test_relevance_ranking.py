"""
tests/test_relevance_ranking.py

Contract tests for the market-relevance scorer and the diversity-aware
ranking post-pass.

Hinges of this feature:

  1. Cross-asset breadth beats magnitude.  An event with 4 channels
     moved ≥1σ outranks one with 1 channel at 3σ.  This is *the* test
     that tells us the scorer is no longer measuring "easy to validate."

  2. Persistence is separate from validation.  A 3σ one-day spike
     that retraced should not outrank a 1σ move that held over 20d.

  3. Validation remains a smaller third component — it still tilts
     among near-equal-relevance events but doesn't dominate.

  4. Diversity post-pass caps over-concentration.  A list of 10
     oil-family events + 2 credit-family events should produce a
     mixed top-N, not 10 oils then 2 credits.

  5. A truly dominant family still wins.  If oil's scores are
     genuinely higher, the decay doesn't force an artificial
     alternation.

  6. Deterministic under ties (tie-breaking by input order).

  7. Pure / safe — malformed input doesn't crash, bool/NaN in the
     return_5d field sanitises, unknown tickers are skipped.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from relevance_ranking import (
    compute_relevance_score,
    rank_with_diversity,
    _CHANNEL_SIGMA_5D_PCT,
    _CLUSTER_DECAY,
    _FAMILY_DECAY,
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _ticker(symbol: str, *, return_5d: float | None = 0.0,
            direction_tag: str | None = "supports thesis") -> dict:
    return {
        "symbol":        symbol,
        "return_5d":     return_5d,
        "direction_tag": direction_tag,
    }


def _event(
    *,
    family: str = "none",
    tickers: list[dict] | None = None,
    persistence: str = "medium",
    stage: str = "realized",
    confidence: str = "medium",
    rating: str = "mixed",
    revisit_snapshots: list[dict] | None = None,
    low_signal: bool = False,
    event_id: int = 1,
) -> dict:
    return {
        "id":                  event_id,
        "mechanism_family":    family,
        "persistence":         persistence,
        "stage":               stage,
        "confidence":          confidence,
        "rating":              rating,
        "market_tickers":      tickers or [],
        "revisit_snapshots":   revisit_snapshots or [],
        "low_signal":          low_signal,
    }


def _one_sigma_ticker(channel: str, symbol: str) -> dict:
    """A ticker moving ≈1σ for its channel — used to populate breadth tests."""
    sigma = _CHANNEL_SIGMA_5D_PCT[channel]
    return _ticker(symbol, return_5d=sigma)


# ---------------------------------------------------------------------------
# Component invariants
# ---------------------------------------------------------------------------


class TestOutputShape(unittest.TestCase):
    def test_keys_present_and_ranges(self) -> None:
        out = compute_relevance_score(_event(
            tickers=[_ticker("XLE", return_5d=2.0)],
        ))
        self.assertIn("overall_score", out)
        self.assertIn("components", out)
        for axis in ("cross_asset_significance", "persistence", "validation"):
            self.assertIn(axis, out["components"])
            self.assertGreaterEqual(out["components"][axis], 0.0)
            self.assertLessEqual(out["components"][axis], 1.0)
        self.assertGreaterEqual(out["overall_score"], 0.0)
        self.assertLessEqual(out["overall_score"], 1.0)

    def test_empty_event_does_not_crash(self) -> None:
        # Empty dict lands on default scores for the persistence /
        # validation components (unknown tags / stage / confidence get a
        # mid-low fallback so one missing field doesn't zero the entire
        # event).  The cross-asset component is 0 without tickers, so
        # the overall score must stay well below any real event's.
        out = compute_relevance_score({})
        self.assertLess(out["overall_score"], 0.25)
        self.assertEqual(
            out["components"]["cross_asset_significance"], 0.0,
        )

    def test_none_input_does_not_crash(self) -> None:
        out = compute_relevance_score(None)  # type: ignore[arg-type]
        self.assertLess(out["overall_score"], 0.25)


# ---------------------------------------------------------------------------
# Cross-asset significance — the new primary signal
# ---------------------------------------------------------------------------


class TestBreadthBeatsMagnitude(unittest.TestCase):
    def test_four_channel_one_sigma_beats_one_channel_three_sigma(self) -> None:
        """The test that tells us the scorer has really moved past
        'easy to validate'."""
        broad = _event(
            tickers=[
                _one_sigma_ticker("equities", "XLE"),
                _one_sigma_ticker("commodities", "USO"),
                _one_sigma_ticker("rates", "TLT"),
                _one_sigma_ticker("credit", "HYG"),
            ],
            event_id=1,
        )
        narrow = _event(
            tickers=[
                _ticker("XLE", return_5d=3 * _CHANNEL_SIGMA_5D_PCT["equities"]),
            ],
            event_id=2,
        )
        broad_score = compute_relevance_score(broad)["components"]
        narrow_score = compute_relevance_score(narrow)["components"]
        self.assertGreater(
            broad_score["cross_asset_significance"],
            narrow_score["cross_asset_significance"],
            "4-channel 1σ event must outscore 1-channel 3σ event on "
            "cross_asset_significance — otherwise ranking still "
            "rewards single-axis magnitude over breadth.",
        )

    def test_no_cross_asset_signal_without_channel_tickers(self) -> None:
        """An event with only unknown-channel tickers scores zero."""
        ev = _event(tickers=[
            _ticker("FOO", return_5d=10.0),
            _ticker("BAR", return_5d=-8.0),
        ])
        self.assertEqual(
            compute_relevance_score(ev)["components"]["cross_asset_significance"],
            0.0,
        )

    def test_multiple_tickers_same_channel_take_max(self) -> None:
        """Two equity tickers, same channel — we use the max move, not the sum."""
        ev = _event(tickers=[
            _ticker("XLE", return_5d=0.5),
            _ticker("XLF", return_5d=3.0),
        ])
        # Max 3.0 / σ 1.5 = 2.0 → channel contribution 2/3; divided by
        # the expected-breadth constant (4.0) → ≈ 0.167.
        score = compute_relevance_score(ev)["components"]["cross_asset_significance"]
        self.assertAlmostEqual(score, (2 / 3) / 4, places=3)

    def test_breadth_bonus_capped(self) -> None:
        """A 6-channel all-1σ event stays within [0, 1]."""
        ev = _event(tickers=[
            _one_sigma_ticker("equities", "XLE"),
            _one_sigma_ticker("commodities", "USO"),
            _one_sigma_ticker("rates", "TLT"),
            _one_sigma_ticker("credit", "HYG"),
        ])
        score = compute_relevance_score(ev)["components"]["cross_asset_significance"]
        self.assertLessEqual(score, 1.0)


class TestCrossAssetSanity(unittest.TestCase):
    def test_nan_return_treated_as_missing(self) -> None:
        ev = _event(tickers=[_ticker("XLE", return_5d=float("nan"))])
        score = compute_relevance_score(ev)["components"]["cross_asset_significance"]
        self.assertEqual(score, 0.0)

    def test_inf_return_treated_as_missing(self) -> None:
        ev = _event(tickers=[_ticker("XLE", return_5d=float("inf"))])
        score = compute_relevance_score(ev)["components"]["cross_asset_significance"]
        self.assertEqual(score, 0.0)

    def test_return_sign_does_not_matter(self) -> None:
        up = _event(tickers=[_ticker("XLE", return_5d=3.0)])
        down = _event(tickers=[_ticker("XLE", return_5d=-3.0)])
        self.assertAlmostEqual(
            compute_relevance_score(up)["components"]["cross_asset_significance"],
            compute_relevance_score(down)["components"]["cross_asset_significance"],
            places=5,
        )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence(unittest.TestCase):
    def test_persistent_beats_one_off(self) -> None:
        persistent = _event(
            persistence="high", stage="realized",
            revisit_snapshots=[{"day": 5, "return_5d": 2.0},
                               {"day": 20, "return_20d": 1.8}],
        )
        one_off = _event(
            persistence="one-off", stage="anticipation",
            revisit_snapshots=[],
        )
        self.assertGreater(
            compute_relevance_score(persistent)["components"]["persistence"],
            compute_relevance_score(one_off)["components"]["persistence"],
        )

    def test_realized_stage_outranks_preview(self) -> None:
        realized = _event(persistence="medium", stage="realized")
        preview = _event(persistence="medium", stage="preview")
        self.assertGreater(
            compute_relevance_score(realized)["components"]["persistence"],
            compute_relevance_score(preview)["components"]["persistence"],
        )

    def test_unknown_stage_degrades_mid_low(self) -> None:
        out = compute_relevance_score(_event(stage="gibberish"))
        self.assertLessEqual(out["components"]["persistence"], 1.0)
        self.assertGreaterEqual(out["components"]["persistence"], 0.0)


# ---------------------------------------------------------------------------
# Validation — retained, but should NOT dominate
# ---------------------------------------------------------------------------


class TestValidationDoesNotDominate(unittest.TestCase):
    def test_high_validation_alone_loses_to_moderate_cross_asset(self) -> None:
        """High confidence + good rating + tags but ZERO cross-asset
        move shouldn't beat a moderate confidence event with a 2σ
        equity move plus decent persistence."""
        pure_validation = _event(
            confidence="high", rating="good",
            tickers=[_ticker("XLE", return_5d=0.0, direction_tag="supports thesis")],
            persistence="low", stage="preview",
        )
        real_move = _event(
            confidence="medium", rating="mixed",
            tickers=[
                _ticker("XLE", return_5d=3.0),
                _ticker("HYG", return_5d=1.5),
            ],
            persistence="medium", stage="realized",
        )
        pv = compute_relevance_score(pure_validation)["overall_score"]
        rm = compute_relevance_score(real_move)["overall_score"]
        self.assertGreater(
            rm, pv,
            f"Market-relevant event ({rm:.3f}) must outrank "
            f"pure-validation event ({pv:.3f}) — otherwise scoring "
            f"still favours 'easy to validate' over 'matters to market'.",
        )

    def test_low_signal_event_penalised(self) -> None:
        normal = _event()
        flagged = _event(low_signal=True)
        self.assertGreater(
            compute_relevance_score(normal)["components"]["validation"],
            compute_relevance_score(flagged)["components"]["validation"],
        )


# ---------------------------------------------------------------------------
# Diversity post-pass
# ---------------------------------------------------------------------------


def _oil_event(event_id: int, *, strong: bool) -> dict:
    """An oil / commodity-squeeze event; ``strong`` toggles intensity."""
    mag = 3.5 if strong else 1.5
    return _event(
        event_id=event_id,
        family="commodity_squeeze",
        tickers=[
            _ticker("USO", return_5d=mag),
            _ticker("XLE", return_5d=mag),
        ],
        persistence="high",
        confidence="high", rating="good",
    )


def _credit_event(event_id: int, *, strong: bool) -> dict:
    mag = 2.0 if strong else 1.0
    return _event(
        event_id=event_id,
        family="bank_stress",
        tickers=[
            _ticker("HYG", return_5d=mag),
            _ticker("LQD", return_5d=mag * 0.6),
        ],
        persistence="high",
        confidence="high", rating="good",
    )


def _ip_event(event_id: int) -> dict:
    """Industrial policy — distinct family, moderate relevance."""
    return _event(
        event_id=event_id,
        family="industrial_policy",
        tickers=[_ticker("SMH", return_5d=2.2)],
        persistence="medium",
        confidence="medium", rating="good",
    )


class TestDiversityPostPass(unittest.TestCase):
    def test_diverse_mix_not_dominated_by_one_family(self) -> None:
        """10 moderate oil events + 3 moderate credit events + 2 IP
        events — the top-5 should have ≥3 distinct families."""
        events = (
            [_oil_event(i, strong=False) for i in range(10)]
            + [_credit_event(100 + i, strong=False) for i in range(3)]
            + [_ip_event(200 + i) for i in range(2)]
        )
        ranked = rank_with_diversity(events, limit=5)
        top5_families = {r["mechanism_family"] for r in ranked}
        self.assertGreaterEqual(
            len(top5_families), 3,
            f"Top-5 collapsed into {top5_families} — diversity post-pass "
            f"isn't shaking out the concentrated family.",
        )

    def test_dominant_event_still_wins_slot_one(self) -> None:
        """If one family's events are overwhelmingly stronger, its
        *first* event wins slot 1 regardless of decay."""
        events = [
            _oil_event(1, strong=True),
            _credit_event(2, strong=False),
            _ip_event(3),
        ]
        ranked = rank_with_diversity(events, limit=3)
        self.assertEqual(ranked[0]["mechanism_family"], "commodity_squeeze")

    def test_dominant_family_can_win_consecutive_slots_if_scores_justify(self) -> None:
        """Oil-oil-oil-oil all at 1.0 vs credit at 0.3 — oil keeps
        winning because 1.0 × 0.7 = 0.70 still beats 0.30."""
        events = (
            [_oil_event(i, strong=True) for i in range(4)]
            + [_credit_event(100, strong=False)]
        )
        ranked = rank_with_diversity(events, limit=4)
        oil_count = sum(
            1 for r in ranked
            if r["mechanism_family"] == "commodity_squeeze"
        )
        self.assertGreaterEqual(
            oil_count, 3,
            "Genuinely dominant oil shouldn't be forced into alternation "
            "by the decay — decay is a soft penalty, not a hard cap.",
        )

    def test_decay_1_disables_diversity(self) -> None:
        """``family_decay=1.0`` is a back-door to pure relevance order."""
        events = (
            [_oil_event(i, strong=False) for i in range(4)]
            + [_credit_event(100, strong=False)]
        )
        ranked = rank_with_diversity(events, limit=5, family_decay=1.0)
        # Every picked event with decay=1.0 has diversity_decay=1.0.
        for r in ranked:
            self.assertAlmostEqual(r["diversity_decay"], 1.0, places=6)

    def test_ranked_output_carries_decomposition(self) -> None:
        ranked = rank_with_diversity([_oil_event(1, strong=True)], limit=1)
        self.assertEqual(len(ranked), 1)
        entry = ranked[0]
        for field in ("overall_score", "effective_score", "components",
                      "mechanism_family", "diversity_decay",
                      "family_rank_in_list", "rank"):
            self.assertIn(field, entry)
        self.assertEqual(entry["family_rank_in_list"], 1)
        self.assertEqual(entry["rank"], 1)

    def test_limit_is_respected(self) -> None:
        events = [_oil_event(i, strong=False) for i in range(20)]
        ranked = rank_with_diversity(events, limit=3)
        self.assertEqual(len(ranked), 3)

    def test_invalid_decay_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_with_diversity([], limit=1, family_decay=0.0)
        with self.assertRaises(ValueError):
            rank_with_diversity([], limit=1, family_decay=1.5)

    def test_invalid_limit_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_with_diversity([], limit=0)

    def test_empty_input_returns_empty(self) -> None:
        self.assertEqual(rank_with_diversity([], limit=5), [])

    def test_malformed_events_skipped(self) -> None:
        ranked = rank_with_diversity(
            [_oil_event(1, strong=True), "not a dict", None, 42],  # type: ignore[list-item]
            limit=5,
        )
        self.assertEqual(len(ranked), 1)


class TestEffectiveScoreDecayMath(unittest.TestCase):
    def test_second_oil_decays_by_combined_axes(self) -> None:
        """Two near-identical oil events share family + transmission
        signature, so the second event's effective score compounds the
        family and cluster decays.  The backward-compatible
        ``diversity_decay`` field still reports the family multiplier
        on its own."""
        events = [_oil_event(1, strong=True), _oil_event(2, strong=True)]
        ranked = rank_with_diversity(events, limit=2)
        first, second = ranked[0], ranked[1]
        self.assertAlmostEqual(first["diversity_decay"],       1.0, places=6)
        self.assertAlmostEqual(first["cluster_decay_applied"], 1.0, places=6)
        self.assertAlmostEqual(second["diversity_decay"],
                               _FAMILY_DECAY,  places=6)
        self.assertAlmostEqual(second["cluster_decay_applied"],
                               _CLUSTER_DECAY, places=6)
        self.assertAlmostEqual(
            second["effective_score"],
            round(second["overall_score"] * _FAMILY_DECAY * _CLUSTER_DECAY, 4),
            places=4,
        )


def _hop(channel: str, actor: str = "actor") -> dict:
    return {"hop": "step", "channel": channel, "actor": actor}


def _oil_with_path(event_id: int, channels: list[str], *,
                   strong: bool = True) -> dict:
    """Oil event carrying an explicit transmission_path.  The channel
    tuple drives the cluster signature so events with different
    ``channels`` land in separate cluster buckets."""
    ev = _oil_event(event_id, strong=strong)
    ev["transmission_path"] = [_hop(c) for c in channels]
    return ev


class TestClusterDecay(unittest.TestCase):
    """Duplicate-cluster decay: events sharing a transmission-path
    signature get penalised harder than events that only share a
    mechanism family.  Keeps one strong representative at the top
    without hiding genuinely distinct events."""

    def test_identical_paths_compound_family_and_cluster_decay(self) -> None:
        # Same family AND same transmission path → both decays stack.
        a = _oil_with_path(1, ["supply", "pricing_power"], strong=True)
        b = _oil_with_path(2, ["supply", "pricing_power"], strong=True)
        ranked = rank_with_diversity([a, b], limit=2)
        self.assertAlmostEqual(ranked[1]["cluster_decay_applied"],
                               _CLUSTER_DECAY, places=6)
        expected = round(
            ranked[1]["overall_score"] * _FAMILY_DECAY * _CLUSTER_DECAY, 4,
        )
        self.assertAlmostEqual(ranked[1]["effective_score"],
                               expected, places=4)

    def test_distinct_paths_same_family_only_family_decay(self) -> None:
        # Two oil events in the same family but with different
        # transmission path shapes land in different cluster buckets
        # — only family_decay applies to the second pick.
        a = _oil_with_path(1, ["supply", "pricing_power"], strong=True)
        b = _oil_with_path(2, ["tariff", "substitution"],  strong=True)
        ranked = rank_with_diversity([a, b], limit=2)
        second = ranked[1]
        self.assertAlmostEqual(second["cluster_decay_applied"], 1.0, places=6)
        self.assertAlmostEqual(second["diversity_decay"],
                               _FAMILY_DECAY, places=6)
        self.assertAlmostEqual(
            second["effective_score"],
            round(second["overall_score"] * _FAMILY_DECAY, 4),
            places=4,
        )

    def test_duplicate_cluster_cedes_slot_to_novel_event(self) -> None:
        """Near-identical oil cluster shouldn't own all top slots.

        Four strong oil events with identical paths + one moderate
        credit event: under the new combined decay, the credit event
        should outrank at least the third identical-oil because
        1.0 × 0.49 × 0.2025 ≈ 0.099 falls below credit's score.
        """
        oils = [
            _oil_with_path(i, ["supply", "pricing_power"], strong=True)
            for i in range(4)
        ]
        credit = _credit_event(100, strong=False)
        ranked = rank_with_diversity(oils + [credit], limit=4)
        families = [r["mechanism_family"] for r in ranked]
        self.assertIn("bank_stress", families,
                      msg=f"credit event never surfaced in {families!r}")
        # Cluster decay must keep oil off at least one slot in the top-4.
        oil_count = sum(1 for f in families if f == "commodity_squeeze")
        self.assertLessEqual(
            oil_count, 3,
            msg="duplicate-path oil cluster still monopolises the top",
        )

    def test_top_slot_still_goes_to_best_relevance(self) -> None:
        """A strong, novel event never loses slot 1 to cluster decay —
        cluster decay kicks in from slot 2 onwards."""
        a = _oil_with_path(1, ["supply", "pricing_power"], strong=True)
        b = _oil_with_path(2, ["supply", "pricing_power"], strong=True)
        ranked = rank_with_diversity([a, b], limit=2)
        self.assertEqual(ranked[0]["cluster_rank_in_list"], 1)
        self.assertAlmostEqual(ranked[0]["effective_score"],
                               ranked[0]["overall_score"], places=4)

    def test_family_decay_one_disables_cluster_decay_too(self) -> None:
        """``family_decay=1.0`` is the single-flag back-door to pure
        relevance order — cluster decay must also bow out."""
        a = _oil_with_path(1, ["supply", "pricing_power"], strong=True)
        b = _oil_with_path(2, ["supply", "pricing_power"], strong=True)
        ranked = rank_with_diversity([a, b], limit=2, family_decay=1.0)
        for r in ranked:
            self.assertAlmostEqual(r["diversity_decay"],       1.0, places=6)
            self.assertAlmostEqual(r["cluster_decay_applied"], 1.0, places=6)

    def test_thin_signature_events_do_not_cluster_decay(self) -> None:
        """Events without family identity (``kind='thin'``) have no
        cluster key, so they never compound decay with each other."""
        thin_a = _event(family="none", event_id=1,
                        tickers=[_ticker("USO", return_5d=3.5)],
                        persistence="high", confidence="high", rating="good")
        thin_b = _event(family="none", event_id=2,
                        tickers=[_ticker("XLE", return_5d=3.5)],
                        persistence="high", confidence="high", rating="good")
        ranked = rank_with_diversity([thin_a, thin_b], limit=2)
        for r in ranked:
            self.assertAlmostEqual(r["cluster_decay_applied"], 1.0, places=6)

    def test_custom_cluster_decay_is_accepted(self) -> None:
        # Callers can tune the cluster axis independently.
        a = _oil_with_path(1, ["supply", "pricing_power"], strong=True)
        b = _oil_with_path(2, ["supply", "pricing_power"], strong=True)
        ranked = rank_with_diversity(
            [a, b], limit=2, cluster_decay=0.20,
        )
        self.assertAlmostEqual(ranked[1]["cluster_decay_applied"],
                               0.20, places=6)

    def test_invalid_cluster_decay_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_with_diversity([], limit=1, cluster_decay=0.0)
        with self.assertRaises(ValueError):
            rank_with_diversity([], limit=1, cluster_decay=1.5)

    def test_response_shape_includes_new_fields(self) -> None:
        ranked = rank_with_diversity([_oil_event(1, strong=True)], limit=1)
        self.assertEqual(len(ranked), 1)
        entry = ranked[0]
        # Existing backward-compat keys still present.
        for legacy in ("overall_score", "effective_score", "components",
                       "mechanism_family", "diversity_decay",
                       "family_rank_in_list", "rank"):
            self.assertIn(legacy, entry)
        # New keys surfaced without breaking the old shape.
        self.assertIn("cluster_decay_applied", entry)
        self.assertIn("cluster_rank_in_list",  entry)
        self.assertEqual(entry["cluster_rank_in_list"], 1)


class TestQualityAdjustment(unittest.TestCase):
    """Per-event quality adjustments — staleness, low-information, and
    the fresh-evidence bonus — shift ordering without touching the
    response shape."""

    _NOW = __import__("datetime").datetime(2026, 4, 20, 12, 0, 0)

    def _base_event(self, *, event_id: int = 1, **overrides) -> dict:
        ev = _oil_event(event_id, strong=True)
        ev.setdefault("event_date", "2026-04-18")
        ev.setdefault("timestamp", "2026-04-18T09:00:00")
        ev.update(overrides)
        return ev

    def test_stale_event_ranks_below_fresh_peer(self) -> None:
        fresh = self._base_event(
            event_id=1,
            last_market_check_at="2026-04-20T09:00:00",  # same day
        )
        stale = self._base_event(
            event_id=2,
            last_market_check_at="2026-02-01T09:00:00",  # 80 days ago
        )
        ranked = rank_with_diversity(
            [stale, fresh], limit=2, now=self._NOW,
        )
        # Fresh must appear before stale even though they're otherwise
        # identical: the staleness penalty is the tiebreaker.
        self.assertEqual(ranked[0]["event"]["id"], 1)
        self.assertEqual(ranked[1]["event"]["id"], 2)

        fresh_score = compute_relevance_score(fresh, now=self._NOW)["overall_score"]
        stale_score = compute_relevance_score(stale, now=self._NOW)["overall_score"]
        self.assertGreater(fresh_score, stale_score)

    def test_legacy_event_loses_to_fresh_peer(self) -> None:
        fresh = self._base_event(
            event_id=1,
            last_market_check_at="2026-04-20T09:00:00",
        )
        # Real archive row but no last_market_check_at → legacy status.
        legacy = self._base_event(event_id=2)
        legacy.pop("last_market_check_at", None)

        fresh_score = compute_relevance_score(fresh, now=self._NOW)["overall_score"]
        legacy_score = compute_relevance_score(legacy, now=self._NOW)["overall_score"]
        self.assertGreater(fresh_score, legacy_score)

    def test_low_info_event_penalised(self) -> None:
        clean = self._base_event(
            event_id=1,
            last_market_check_at="2026-04-20T09:00:00",
            mechanism_summary=(
                "Refinery outage tightens Gulf Coast cracking capacity "
                "and widens the WCS-WTI discount."
            ),
            confidence="low",
        )
        low_info = self._base_event(
            event_id=2,
            last_market_check_at="2026-04-20T09:00:00",
            mechanism_summary="Insufficient evidence to characterise the mechanism.",
            confidence="low",
        )
        clean_score = compute_relevance_score(clean, now=self._NOW)["overall_score"]
        low_info_score = compute_relevance_score(low_info, now=self._NOW)["overall_score"]
        self.assertGreater(clean_score, low_info_score)

    def test_low_info_penalty_requires_low_confidence(self) -> None:
        """A high-confidence event with tentative-sounding mechanism
        text is NOT punished — the penalty requires both signals."""
        high_conf = self._base_event(
            event_id=1,
            last_market_check_at="2026-04-20T09:00:00",
            mechanism_summary="Insufficient evidence to characterise.",
            confidence="high",
        )
        # Drop any stale marker by keeping last_market_check fresh.
        out = compute_relevance_score(high_conf, now=self._NOW)
        # No low-info reason recorded in explanation.
        self.assertNotIn("low-information", out["explanation"])

    def test_fresh_evidence_bonus_rewards_strong_aggregate(self) -> None:
        # The basket needs a primary single-name in support; otherwise the
        # broad-beta filter (validation_outcome.score_weighted_evidence)
        # downgrades an all-ETF supportive aggregate to ``mixed`` and the
        # bonus never fires.  CVX is a primary single-name; XLE is its
        # secondary corroborating ETF.
        strong_ev = self._base_event(
            event_id=1,
            last_market_check_at="2026-04-20T09:00:00",
            market_tickers=[
                {"symbol": "CVX", "role": "beneficiary",
                 "return_5d": 3.0, "direction_tag": "supports",
                 "evidence_score":  0.9,
                 "evidence_label": "supportive"},
                {"symbol": "XLE", "role": "beneficiary",
                 "return_5d": 3.0, "direction_tag": "supports",
                 "evidence_score":  0.8,
                 "evidence_label": "supportive"},
            ],
        )
        weak_ev = self._base_event(
            event_id=2,
            last_market_check_at="2026-04-20T09:00:00",
            market_tickers=[
                {"symbol": "CVX", "role": "beneficiary",
                 "return_5d": 3.0, "direction_tag": "supports"},
                {"symbol": "XLE", "role": "beneficiary",
                 "return_5d": 3.0, "direction_tag": "supports"},
            ],
        )
        strong_score = compute_relevance_score(strong_ev, now=self._NOW)["overall_score"]
        weak_score = compute_relevance_score(weak_ev, now=self._NOW)["overall_score"]
        self.assertGreater(strong_score, weak_score)

    def test_tag_only_cohort_does_not_trigger_bonus(self) -> None:
        """Tag-only unanimous cohort aggregates to 0.5 — below the
        0.60 fresh-evidence floor — so no bonus is applied."""
        ev = self._base_event(
            event_id=1,
            last_market_check_at="2026-04-20T09:00:00",
            market_tickers=[
                {"symbol": "USO", "role": "beneficiary",
                 "return_5d": 3.0, "direction_tag": "supports"},
                {"symbol": "XLE", "role": "beneficiary",
                 "return_5d": 3.0, "direction_tag": "supports"},
            ],
        )
        out = compute_relevance_score(ev, now=self._NOW)
        self.assertNotIn("supportive evidence", out["explanation"])


class TestWeakSiblingClusterDecay(unittest.TestCase):
    """The weakest sibling inside a duplicate-cluster should take an
    extra tick of cluster decay, so it doesn't colonise a slot just
    because it shares a theme with a strong representative."""

    def _path(self, channels, event_id, *, strong):
        ev = _oil_event(event_id, strong=strong)
        ev["transmission_path"] = [_hop(c) for c in channels]
        return ev

    def _genuinely_weak_sibling(self, event_id: int) -> dict:
        """A same-cluster sibling whose overall score is well below
        the strong representative — low confidence, thin ticker set,
        and short persistence.  Its score ratio to a strong oil
        representative lands under the 0.80 weak-sibling threshold."""
        ev = _event(
            event_id=event_id,
            family="commodity_squeeze",
            tickers=[_ticker("USO", return_5d=1.0)],
            persistence="low",
            stage="preview",
            confidence="low",
            rating="mixed",
        )
        ev["transmission_path"] = [_hop("supply"), _hop("pricing_power")]
        return ev

    def test_weaker_sibling_takes_extra_decay(self) -> None:
        strong = self._path(["supply", "pricing_power"], 1, strong=True)
        weak = self._genuinely_weak_sibling(event_id=2)
        ranked = rank_with_diversity([strong, weak], limit=2)
        # Representative gets cluster_mult = 1.0 (first in cluster).
        self.assertAlmostEqual(
            ranked[0]["cluster_decay_applied"], 1.0, places=6,
        )
        # Weak sibling score/rep ratio < 0.80 → one extra tick:
        # cluster_decay^(prior + 1) = 0.45 * 0.45 = 0.2025.
        self.assertAlmostEqual(
            ranked[1]["cluster_decay_applied"],
            _CLUSTER_DECAY * _CLUSTER_DECAY,
            places=4,
            msg=f"weak sibling got {ranked[1]['cluster_decay_applied']} — "
                f"expected {_CLUSTER_DECAY * _CLUSTER_DECAY}",
        )

    def test_equal_strength_siblings_use_flat_cluster_decay(self) -> None:
        a = self._path(["supply", "pricing_power"], 1, strong=True)
        b = self._path(["supply", "pricing_power"], 2, strong=True)
        ranked = rank_with_diversity([a, b], limit=2)
        self.assertAlmostEqual(
            ranked[1]["cluster_decay_applied"], _CLUSTER_DECAY, places=6,
        )


class TestBreadthAcrossTransmissionPaths(unittest.TestCase):
    """The broader-topic philosophy: ranking should favour novelty +
    market relevance, not default to oil/war density when multiple
    events have the same transmission shape."""

    def test_top_3_covers_multiple_clusters_when_one_family_overrepresented(self) -> None:
        """Five oil events with identical transmission paths + two
        genuinely different oil paths should surface a top-3 that
        covers more than a single cluster bucket."""
        duplicates = [
            _oil_with_path(i, ["supply", "pricing_power"], strong=True)
            for i in range(5)
        ]
        novel1 = _oil_with_path(100, ["tariff", "substitution"],
                                strong=True)
        novel2 = _oil_with_path(101, ["regulatory", "capital_flow"],
                                strong=True)
        ranked = rank_with_diversity(
            duplicates + [novel1, novel2], limit=3,
        )
        cluster_ranks = [r["cluster_rank_in_list"] for r in ranked]
        # At least two entries in the top-3 should come from their
        # own cluster (cluster_rank_in_list == 1) — otherwise a
        # single path shape is owning the list.
        first_in_cluster_count = sum(1 for k in cluster_ranks if k == 1)
        self.assertGreaterEqual(
            first_in_cluster_count, 2,
            msg=f"top-3 cluster ranks {cluster_ranks!r} — one path "
                "shape is dominating despite novel alternatives.",
        )


if __name__ == "__main__":
    unittest.main()
