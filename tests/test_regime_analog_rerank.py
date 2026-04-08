"""
tests/test_regime_analog_rerank.py

Focused tests for the regime-conditioned analog re-ranker.

Three required scenarios:
  1. Same-topic but different-regime analogs rank LOWER than same-topic
     same-regime peers.
  2. Lower-topic but better-regime analogs rank HIGHER than higher-topic
     worse-regime peers.
  3. Stale / unavailable macro context degrades cleanly — the rerank
     becomes a no-op and the original order survives.

Plus supporting coverage for the regime vector composer, the distance
metric, and the match-reason string.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from regime_vector import (  # noqa: E402
    build_regime_vector,
    regime_distance,
    regime_match_reason,
    rerank_analogs,
    REGIME_AXES,
    TOPIC_WEIGHT,
    REGIME_WEIGHT,
    NEUTRAL_REGIME_MATCH,
)


# ---------------------------------------------------------------------------
# Fixtures — mirror compute_rates_context / compute_stress_regime shapes
# ---------------------------------------------------------------------------

def _rates(regime: str = "Mixed", nominal_5d=None, real_5d=None,
           breakeven_5d=None) -> dict:
    return {
        "regime": regime,
        "nominal": {"label": "10Y yield", "value": 4.25, "change_5d": nominal_5d},
        "real_proxy": {
            "label": "TIP (real yield proxy)",
            "value": 108.5,
            "change_5d": real_5d,
        },
        "breakeven_proxy": {"label": "Breakeven proxy", "change_5d": breakeven_5d},
        "raw": {"^TNX": 4.25, "TIP": 108.5},
    }


def _stress(
    regime: str = "Calm",
    *,
    safe_haven_bid: bool = False,
    credit_widening: bool = False,
    vix_elevated: bool = False,
    dollar_5d: float | None = None,
) -> dict:
    detail = {}
    if dollar_5d is not None:
        detail["safe_haven"] = {
            "label": "Safe Haven Flows",
            "assets": {"Gold": 0.0, "Dollar": dollar_5d, "Long Bonds": 0.0},
            "inflow_count": 1,
            "status": "calm",
            "explanation": "",
        }
    return {
        "regime": regime,
        "signals": {
            "vix_elevated": vix_elevated,
            "term_inversion": False,
            "credit_widening": credit_widening,
            "safe_haven_bid": safe_haven_bid,
            "breadth_deterioration": False,
        },
        "raw": {"vix": 17.0},
        "detail": detail,
    }


def _snap(market: str, change_5d: float, value: float = 100.0) -> dict:
    return {
        "market": market,
        "symbol": market,
        "value": value,
        "change_5d": change_5d,
        "error": None,
    }


def _vec(infl="neutral", pol="neutral", fx="neutral", gs="neutral",
         available=True, stale=False) -> dict:
    return {
        "inflation":     infl,
        "policy_stance": pol,
        "fx":            fx,
        "growth_stress": gs,
        "available":     available,
        "stale":         stale,
    }


# ---------------------------------------------------------------------------
# build_regime_vector
# ---------------------------------------------------------------------------

class TestBuildRegimeVector(unittest.TestCase):

    def test_inflation_pressure_marks_hot_and_hawkish(self):
        rv = build_regime_vector(
            _rates("Inflation pressure",
                   nominal_5d=0.5, real_5d=-0.5, breakeven_5d=0.4),
            _stress("Calm"),
            [_snap("DXY", 1.5)],
        )
        self.assertEqual(rv["inflation"], "hot")
        self.assertEqual(rv["policy_stance"], "hawkish")
        self.assertEqual(rv["fx"], "dollar_strong")
        self.assertEqual(rv["growth_stress"], "calm")
        self.assertTrue(rv["available"])
        self.assertFalse(rv["stale"])

    def test_risk_off_marks_cool_dovish_stressed(self):
        rv = build_regime_vector(
            _rates("Risk-off / growth scare",
                   nominal_5d=-0.5, real_5d=0.6, breakeven_5d=-0.4),
            _stress("Risk-off / growth scare", safe_haven_bid=True,
                    credit_widening=True),
            [_snap("DXY", -1.5)],
        )
        self.assertEqual(rv["inflation"], "cool")
        self.assertEqual(rv["policy_stance"], "dovish")
        self.assertEqual(rv["fx"], "dollar_weak")
        self.assertEqual(rv["growth_stress"], "stressed")
        self.assertTrue(rv["available"])

    def test_no_macro_returns_unavailable(self):
        rv = build_regime_vector(None, None, None)
        self.assertFalse(rv["available"])
        self.assertTrue(rv["stale"])
        for axis in REGIME_AXES:
            self.assertEqual(rv[axis], "neutral")

    def test_partial_macro_marks_stale_but_available(self):
        rv = build_regime_vector(
            _rates("Inflation pressure",
                   nominal_5d=0.5, real_5d=-0.5, breakeven_5d=0.4),
            None,
            None,
        )
        self.assertTrue(rv["available"])
        self.assertTrue(rv["stale"])
        self.assertEqual(rv["inflation"], "hot")

    def test_fx_falls_back_to_stress_dollar_when_no_snapshot(self):
        rv = build_regime_vector(
            _rates("Inflation pressure",
                   nominal_5d=0.5, real_5d=-0.5, breakeven_5d=0.3),
            _stress("Calm", dollar_5d=1.6),
            snapshots=None,
        )
        self.assertEqual(rv["fx"], "dollar_strong")


# ---------------------------------------------------------------------------
# regime_distance + regime_match_reason
# ---------------------------------------------------------------------------

class TestRegimeDistance(unittest.TestCase):

    def test_perfect_match_is_one(self):
        a = _vec("hot", "hawkish", "dollar_strong", "calm")
        self.assertEqual(regime_distance(a, a), 1.0)

    def test_no_overlap_is_zero(self):
        a = _vec("hot", "hawkish", "dollar_strong", "calm")
        b = _vec("cool", "dovish", "dollar_weak", "stressed")
        self.assertEqual(regime_distance(a, b), 0.0)

    def test_partial_overlap(self):
        a = _vec("hot", "hawkish", "dollar_strong", "calm")
        b = _vec("hot", "hawkish", "dollar_weak", "stressed")  # 2 of 4 match
        self.assertEqual(regime_distance(a, b), 0.5)

    def test_unavailable_returns_none(self):
        a = _vec("hot", "hawkish", "dollar_strong", "calm")
        b = _vec(available=False)
        self.assertIsNone(regime_distance(a, b))
        self.assertIsNone(regime_distance(None, a))


class TestRegimeMatchReason(unittest.TestCase):

    def test_mentions_same_axes(self):
        cur = _vec("hot", "hawkish", "dollar_strong", "calm")
        hist = _vec("hot", "hawkish", "neutral", "neutral")
        reason = regime_match_reason(cur, hist)
        self.assertIn("inflation", reason)
        self.assertIn("policy", reason)

    def test_mentions_opposite_axes(self):
        cur = _vec("hot", "hawkish", "dollar_strong", "calm")
        hist = _vec("cool", "dovish", "dollar_weak", "stressed")
        reason = regime_match_reason(cur, hist)
        self.assertIn("opposite", reason)

    def test_empty_when_unavailable(self):
        cur = _vec("hot", "hawkish", "dollar_strong", "calm")
        self.assertEqual(regime_match_reason(cur, None), "")
        self.assertEqual(regime_match_reason(cur, _vec(available=False)), "")


# ---------------------------------------------------------------------------
# Required scenario 1 — same topic / different regime ranks lower
# ---------------------------------------------------------------------------

class TestSameTopicDifferentRegimeRanksLower(unittest.TestCase):

    def test_same_topic_same_regime_wins(self):
        current = _vec("hot", "hawkish", "dollar_strong", "calm")
        analogs = [
            {
                "id": "diff_regime",
                "similarity": 0.45,
                "regime_snapshot": _vec("cool", "dovish", "dollar_weak", "stressed"),
                "match_reason": "shared: opec, supply",
            },
            {
                "id": "same_regime",
                "similarity": 0.45,
                "regime_snapshot": _vec("hot", "hawkish", "dollar_strong", "calm"),
                "match_reason": "shared: opec, supply",
            },
        ]
        ranked = rerank_analogs(analogs, current)
        self.assertEqual(ranked[0]["id"], "same_regime")
        self.assertEqual(ranked[1]["id"], "diff_regime")
        # And the reason string should carry the regime explanation.
        self.assertIn("regime:", ranked[0]["match_reason"])
        self.assertIn("same inflation", ranked[0]["match_reason"])

    def test_rerank_attaches_scores(self):
        current = _vec("hot", "hawkish", "dollar_strong", "calm")
        analogs = [
            {
                "id": "a",
                "similarity": 0.40,
                "regime_snapshot": _vec("hot", "hawkish", "dollar_strong", "calm"),
                "match_reason": "shared: x",
            },
        ]
        ranked = rerank_analogs(analogs, current)
        self.assertIn("final_score", ranked[0])
        self.assertEqual(ranked[0]["regime_match"], 1.0)
        expected = TOPIC_WEIGHT * 0.40 + REGIME_WEIGHT * 1.0
        self.assertAlmostEqual(ranked[0]["final_score"], round(expected, 3))


# ---------------------------------------------------------------------------
# Required scenario 2 — lower topic but better regime ranks higher
# ---------------------------------------------------------------------------

class TestLowerTopicBetterRegimeRanksHigher(unittest.TestCase):

    def test_low_topic_good_regime_beats_high_topic_bad_regime(self):
        current = _vec("hot", "hawkish", "dollar_strong", "calm")
        analogs = [
            {
                "id": "high_topic_bad_regime",
                "similarity": 0.45,
                "regime_snapshot": _vec("cool", "dovish", "dollar_weak", "stressed"),
                "match_reason": "shared: tariff, supply",
            },
            {
                "id": "low_topic_good_regime",
                "similarity": 0.22,
                "regime_snapshot": _vec("hot", "hawkish", "dollar_strong", "calm"),
                "match_reason": "shared: tariff",
            },
        ]
        ranked = rerank_analogs(analogs, current)
        self.assertEqual(ranked[0]["id"], "low_topic_good_regime")

    def test_neutral_baseline_keeps_old_rows_competitive(self):
        current = _vec("hot", "hawkish", "dollar_strong", "calm")
        analogs = [
            {
                "id": "modern_good",
                "similarity": 0.30,
                "regime_snapshot": _vec("hot", "hawkish", "dollar_strong", "calm"),
                "match_reason": "shared: x",
            },
            {
                "id": "old_no_snapshot",
                "similarity": 0.30,
                "regime_snapshot": None,
                "match_reason": "shared: x",
            },
            {
                "id": "modern_bad",
                "similarity": 0.30,
                "regime_snapshot": _vec("cool", "dovish", "dollar_weak", "stressed"),
                "match_reason": "shared: x",
            },
        ]
        ranked = rerank_analogs(analogs, current)
        ids = [a["id"] for a in ranked]
        # modern_good (1.0) > old_no_snapshot (NEUTRAL 0.5) > modern_bad (0.0)
        self.assertEqual(ids, ["modern_good", "old_no_snapshot", "modern_bad"])
        self.assertIsNone(ranked[1]["regime_match"])  # fallback
        expected_mid = TOPIC_WEIGHT * 0.30 + REGIME_WEIGHT * NEUTRAL_REGIME_MATCH
        self.assertAlmostEqual(ranked[1]["final_score"], round(expected_mid, 3))


# ---------------------------------------------------------------------------
# Required scenario 3 — stale / unavailable macro degrades cleanly
# ---------------------------------------------------------------------------

class TestStaleMacroDegradesCleanly(unittest.TestCase):

    def test_unavailable_current_vector_is_noop(self):
        stale = _vec(available=False, stale=True)
        original = [
            {"id": "first", "similarity": 0.30,
             "regime_snapshot": _vec("cool", "dovish", "dollar_weak", "stressed")},
            {"id": "second", "similarity": 0.40,
             "regime_snapshot": _vec("hot", "hawkish", "dollar_strong", "calm")},
            {"id": "third", "similarity": 0.25, "regime_snapshot": None},
        ]
        ranked = rerank_analogs(list(original), stale)
        self.assertEqual([a["id"] for a in ranked], ["first", "second", "third"])
        # No final_score or regime_match fields should have been injected.
        for a in ranked:
            self.assertNotIn("final_score", a)
            self.assertNotIn("regime_match", a)

    def test_none_vector_is_noop(self):
        original = [
            {"id": "x", "similarity": 0.40, "regime_snapshot": None},
            {"id": "y", "similarity": 0.30, "regime_snapshot": None},
        ]
        ranked = rerank_analogs(list(original), None)
        self.assertEqual([a["id"] for a in ranked], ["x", "y"])

    def test_empty_analog_list_is_passthrough(self):
        current = _vec("hot", "hawkish", "dollar_strong", "calm")
        self.assertEqual(rerank_analogs([], current), [])


# ---------------------------------------------------------------------------
# end-to-end db.find_historical_analogs wiring (in-memory db fixture)
# ---------------------------------------------------------------------------

class TestFindHistoricalAnalogsWithRegime(unittest.TestCase):
    """Exercise db.find_historical_analogs against a real sqlite file.

    Uses a temp DB so we don't touch the developer's events.db.
    """

    def setUp(self):
        import tempfile
        import db
        self._tmpdir = tempfile.mkdtemp()
        self._orig_db_file = db.DB_FILE
        db.DB_FILE = os.path.join(self._tmpdir, "test_events.db")
        db.init_db()
        self._db = db

        # Seed two saved events with opposing regime backdrops but the
        # same topic words so the rerank has something meaningful to
        # reshuffle.
        hot_regime = _vec("hot", "hawkish", "dollar_strong", "calm")
        cool_regime = _vec("cool", "dovish", "dollar_weak", "stressed")

        db.save_event({
            "headline": "OPEC cuts output sharply in supply shock",
            "stage": "unfolding",
            "persistence": "structural",
            "mechanism_summary": "OPEC supply shock lifts crude price",
            "beneficiaries": [], "losers": [], "assets_to_watch": [],
            "confidence": "high",
            "market_note": "",
            "market_tickers": [{"symbol": "XOM", "return_5d": 3.2, "return_20d": 5.1}],
            "event_date": "2024-06-01",
            "notes": "",
            "model": "test",
            "transmission_chain": [],
            "if_persists": {}, "currency_channel": {},
            "policy_sensitivity": {}, "inventory_context": {},
            "regime_snapshot": hot_regime,
            "low_signal": 0,
        })
        db.save_event({
            "headline": "OPEC cuts output amid demand destruction",
            "stage": "unfolding",
            "persistence": "structural",
            "mechanism_summary": "OPEC supply shock amid collapsing demand",
            "beneficiaries": [], "losers": [], "assets_to_watch": [],
            "confidence": "high",
            "market_note": "",
            "market_tickers": [{"symbol": "XOM", "return_5d": -2.1, "return_20d": -3.0}],
            "event_date": "2024-06-02",
            "notes": "",
            "model": "test",
            "transmission_chain": [],
            "if_persists": {}, "currency_channel": {},
            "policy_sensitivity": {}, "inventory_context": {},
            "regime_snapshot": cool_regime,
            "low_signal": 0,
        })

    def tearDown(self):
        import shutil
        self._db.DB_FILE = self._orig_db_file
        self._db._db_ready = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_regime_rerank_reorders_analogs(self):
        current = _vec("hot", "hawkish", "dollar_strong", "calm")
        results = self._db.find_historical_analogs(
            "OPEC slashes output in new supply shock",
            mechanism="Crude price spike on production cut",
            stage="unfolding",
            persistence="structural",
            exclude_headline="OPEC slashes output in new supply shock",
            limit=2,
            current_regime_vector=current,
        )
        self.assertEqual(len(results), 2)
        # Same-regime analog must come first.
        self.assertIn("supply shock", results[0]["headline"].lower())
        self.assertIn("regime:", results[0]["match_reason"])
        # Each result should carry the rerank fields.
        self.assertIn("final_score", results[0])

    def test_no_regime_falls_back_to_topic_only(self):
        # Same call, but no current regime vector — should still return
        # analogs, just without rerank fields.
        results = self._db.find_historical_analogs(
            "OPEC slashes output in new supply shock",
            mechanism="Crude price spike on production cut",
            stage="unfolding",
            persistence="structural",
            exclude_headline="OPEC slashes output in new supply shock",
            limit=2,
            current_regime_vector=None,
        )
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertNotIn("final_score", r)

    def test_stale_regime_vector_is_noop(self):
        stale = _vec(available=False, stale=True)
        results = self._db.find_historical_analogs(
            "OPEC slashes output in new supply shock",
            mechanism="Crude price spike on production cut",
            stage="unfolding",
            persistence="structural",
            exclude_headline="OPEC slashes output in new supply shock",
            limit=2,
            current_regime_vector=stale,
        )
        self.assertEqual(len(results), 2)
        # Stale vector: behaves exactly like topic-only, no rerank fields.
        for r in results:
            self.assertNotIn("final_score", r)


if __name__ == "__main__":
    unittest.main()
