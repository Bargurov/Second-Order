"""T2A — validate-first naive-baseline characterization (read-only, pure).

The baseline answers the skeptic's first question: are the observed
support / contradiction / unresolved outcomes meaningfully different from a
marginal-preserving null, or mostly the corpus's own drift?

The null is a PERMUTATION null, not a fair coin: a fair-coin (p=0.5) null is
only correct when predicted directions are balanced ~50/50.  This corpus is
beneficiary-heavy (predicted-up ~67%) in a down-drifting window (~41% of names
rose), so a coin null would manufacture a spurious "below chance" reading.  The
permutation shuffles the predicted-direction (role) labels across directional
ticker-observations while holding realized moves fixed, then re-applies the
LIVE majority rule (supporting strictly > contradicting => validated, ties =>
contradicted).  That preserves both marginals and destroys only the
thesis-to-asset linkage.

Pure functions, fixture-driven, deterministic with a fixed seed.  No DB, no
provider, no network.
"""

import re
import unittest

from stats.baseline_characterization import (
    directional_observations,
    support_contradict_counts,
    is_null_validated,
    build_baseline_characterization,
    event_study_split,
    ar_sign_observation,
    build_ar_sign_characterization,
    build_ar_sign_report,
)


def _tk(role, tag):
    return {"symbol": "X", "role": role, "direction_tag": tag}


def _ev(tickers, **kw):
    base = {"id": 1, "market_tickers": tickers, "mechanism_summary": "m",
            "event_date": "2026-01-01"}
    base.update(kw)
    return base


# Directional fixtures (role + tag fully determine predicted_up / realized_up).
A_VALIDATED = _ev([_tk("beneficiary", "supports"), _tk("beneficiary", "supports"),
                   _tk("beneficiary", "supports"), _tk("loser", "contradicts")])  # 3 sup / 1 con
B_CONTRA = _ev([_tk("beneficiary", "contradicts"), _tk("loser", "supports"),
                _tk("loser", "supports"), _tk("beneficiary", "contradicts")])      # 1 sup / 3 con
C_UNRESOLVED = _ev([_tk("beneficiary", "neutral"), _tk("loser", "neutral")])       # tagged, 0 directional
D_NO_TICKERS = _ev([])                                                             # excluded from scored


class TestDirectionalObservations(unittest.TestCase):
    def test_role_and_tag_map_to_predicted_and_realized_direction(self):
        # beneficiary = predicted up; realized up iff (beneficiary & supports) or (loser & contradicts)
        ev = _ev([_tk("beneficiary", "supports"),   # pred up,  real up   -> support
                  _tk("beneficiary", "contradicts"),# pred up,  real down -> contradict
                  _tk("loser", "supports"),          # pred down,real down -> support
                  _tk("loser", "contradicts")])      # pred down,real up   -> contradict
        obs = directional_observations(ev)
        self.assertEqual(obs, [(True, True), (True, False), (False, False), (False, True)])

    def test_non_directional_and_roleless_tickers_are_skipped(self):
        ev = _ev([_tk("beneficiary", "neutral"), _tk("", "supports"), _tk("beneficiary", "supports")])
        self.assertEqual(directional_observations(ev), [(True, True)])


class TestSupportCountsFidelity(unittest.TestCase):
    def test_support_contradict_counts_match_the_live_scorer(self):
        from validation_status import score_validation_status
        for ev in (A_VALIDATED, B_CONTRA):
            sup, con = support_contradict_counts(ev)
            counts = score_validation_status(ev)["counts"]
            self.assertEqual((sup, con), (counts["supporting"], counts["contradicting"]))


class TestNullMajorityRule(unittest.TestCase):
    def test_validated_requires_strict_support_majority_ties_go_to_contradicted(self):
        self.assertTrue(is_null_validated(3, 4))    # 3 > 1
        self.assertFalse(is_null_validated(2, 4))   # tie -> contradicted
        self.assertFalse(is_null_validated(1, 4))
        self.assertTrue(is_null_validated(2, 3))    # 2 > 1
        self.assertFalse(is_null_validated(0, 0))   # not directional


class TestPermutationNull(unittest.TestCase):
    def test_deterministic_with_fixed_seed(self):
        events = [A_VALIDATED, B_CONTRA, C_UNRESOLVED, D_NO_TICKERS]
        r1 = build_baseline_characterization(events, seed=7, n_sims=300)
        r2 = build_baseline_characterization(events, seed=7, n_sims=300)
        self.assertEqual(r1["baseline"], r2["baseline"])

    def test_null_support_rate_tracks_the_marginal_preserving_formula(self):
        # Balanced roles (a=0.5) with mixed realized moves -> null support ~ 0.5.
        balanced = [_ev([_tk("beneficiary", "supports"), _tk("loser", "supports"),
                         _tk("beneficiary", "contradicts"), _tk("loser", "contradicts")])]
        res = build_baseline_characterization(balanced, seed=11, n_sims=1000)
        self.assertAlmostEqual(res["baseline"]["null_support_rate_mean"], 0.5, delta=0.06)


class TestObservedContract(unittest.TestCase):
    def setUp(self):
        self.res = build_baseline_characterization(
            [A_VALIDATED, B_CONTRA, C_UNRESOLVED, D_NO_TICKERS], seed=20260608, n_sims=500)

    def test_scored_set_excludes_zero_ticker_events(self):
        o = self.res["observed"]
        self.assertEqual(o["total_scored"], 3)  # A, B, C (D has no tickers)

    def test_outcome_counts_sum_to_total_scored_unresolved_not_dropped(self):
        o = self.res["observed"]
        self.assertEqual(o["any_supporting"], 1)
        self.assertEqual(o["contradicted"], 1)
        self.assertEqual(o["unresolved"], 1)
        self.assertEqual(o["any_supporting"] + o["contradicted"] + o["unresolved"], o["total_scored"])

    def test_directional_events_exclude_unresolved(self):
        self.assertEqual(self.res["observed"]["directional_events"], 2)  # A, B only


class TestEventStudySplit(unittest.TestCase):
    def test_splits_scored_events_by_injected_event_study_availability(self):
        # Inject a deterministic event-study fn; only the first scored event is available.
        def fake_es(ev):
            return {"status": "event_study_available" if ev is A_VALIDATED else "insufficient_data"}

        split = event_study_split([A_VALIDATED, B_CONTRA, D_NO_TICKERS], fake_es)
        self.assertEqual(split["scored"], 2)  # D has no tickers -> excluded
        self.assertEqual(split["event_study_available"], 1)
        self.assertEqual(split["event_study_unavailable"], 1)

    def test_engine_error_degrades_to_unavailable_never_raises(self):
        def boom(ev):
            raise RuntimeError("engine blew up")

        split = event_study_split([A_VALIDATED], boom)
        self.assertEqual(split["event_study_available"], 0)
        self.assertEqual(split["event_study_unavailable"], 1)


# ---------------------------------------------------------------------------
# T2B — benchmark-adjusted AR-sign disentangler
# ---------------------------------------------------------------------------


def _es_block(ar_by_h, primary="X"):
    return {
        "status": "event_study_available",
        "primary_ticker": primary,
        "per_horizon": [{"horizon": h, "abnormal_return": ar} for h, ar in ar_by_h.items()],
    }


def _ev_primary(role, sym="X"):
    return {"id": 1, "market_tickers": [{"symbol": sym, "role": role, "direction_tag": "supports"}],
            "mechanism_summary": "m", "event_date": "2026-01-01"}


class TestArSignMapping(unittest.TestCase):
    def test_beneficiary_with_positive_ar_is_support(self):
        self.assertEqual(ar_sign_observation(_ev_primary("beneficiary"), _es_block({1: 0.02}), 1),
                         (True, True))

    def test_beneficiary_with_negative_ar_is_contradiction(self):
        self.assertEqual(ar_sign_observation(_ev_primary("beneficiary"), _es_block({1: -0.02}), 1),
                         (True, False))

    def test_loser_with_negative_ar_is_support(self):
        self.assertEqual(ar_sign_observation(_ev_primary("loser"), _es_block({1: -0.02}), 1),
                         (False, False))

    def test_loser_with_positive_ar_is_contradiction(self):
        self.assertEqual(ar_sign_observation(_ev_primary("loser"), _es_block({1: 0.02}), 1),
                         (False, True))

    def test_zero_ar_is_excluded(self):
        self.assertIsNone(ar_sign_observation(_ev_primary("beneficiary"), _es_block({1: 0.0}), 1))

    def test_missing_ar_for_horizon_is_excluded(self):
        self.assertIsNone(ar_sign_observation(_ev_primary("beneficiary"), _es_block({5: 0.02}), 1))

    def test_primary_without_beneficiary_or_loser_role_is_excluded(self):
        self.assertIsNone(ar_sign_observation(_ev_primary("primary"), _es_block({1: 0.02}), 1))


class TestArSignCharacterization(unittest.TestCase):
    def _events(self, specs):
        # specs: list of (role, ar) -> one event each; injected es_fn returns the AR.
        evs = []
        for i, (role, ar) in enumerate(specs):
            ev = _ev_primary(role, sym=f"T{i}")
            ev["_ar"] = ar
            evs.append(ev)
        return evs

    def _es_fn(self, ev):
        return _es_block({1: ev["_ar"], 5: ev["_ar"], 20: ev["_ar"]}, primary=ev["market_tickers"][0]["symbol"])

    def test_deterministic_with_fixed_seed(self):
        evs = self._events([("beneficiary", 0.02), ("loser", -0.01), ("beneficiary", -0.03), ("loser", 0.04)])
        r1 = build_ar_sign_characterization(evs, self._es_fn, horizon=1, seed=3, n_sims=300)
        r2 = build_ar_sign_characterization(evs, self._es_fn, horizon=1, seed=3, n_sims=300)
        self.assertEqual(r1["baseline"], r2["baseline"])

    def test_degenerate_predicted_marginal_is_flagged_not_reliable(self):
        # All beneficiaries -> predicted-up marginal == 1.0 -> permutation null degenerate.
        evs = self._events([("beneficiary", 0.02), ("beneficiary", -0.01), ("beneficiary", -0.03)])
        res = build_ar_sign_characterization(evs, self._es_fn, horizon=1, seed=1, n_sims=200)
        self.assertEqual(res["predicted_up_fraction"], 1.0)
        self.assertFalse(res["reliable"])

    def test_mixed_roles_with_enough_observations_is_reliable(self):
        specs = [("beneficiary", 0.02)] * 8 + [("loser", -0.02)] * 8
        res = build_ar_sign_characterization(self._events(specs), self._es_fn, horizon=1, seed=1, n_sims=200)
        self.assertGreater(res["predicted_up_fraction"], 0.0)
        self.assertLess(res["predicted_up_fraction"], 1.0)
        self.assertTrue(res["reliable"])

    def test_counts_split_into_supporting_contradicting(self):
        evs = self._events([("beneficiary", 0.02), ("beneficiary", -0.01)])
        res = build_ar_sign_characterization(evs, self._es_fn, horizon=1, seed=1, n_sims=50)
        self.assertEqual(res["eligible"], 2)
        self.assertEqual(res["any_supporting"], 1)   # +AR beneficiary supports
        self.assertEqual(res["contradicted"], 1)     # -AR beneficiary contradicts


class TestArSignReport(unittest.TestCase):
    def _es_fn(self, ev):
        return _es_block({1: 0.02, 5: -0.01, 20: 0.03}, primary=ev["market_tickers"][0]["symbol"])

    def test_report_covers_all_three_horizons_with_non_claims(self):
        evs = [_ev_primary("beneficiary", sym=f"T{i}") for i in range(4)]
        rep = build_ar_sign_report(evs, self._es_fn, seed=1, n_sims=100)
        self.assertEqual(set(rep["horizons"].keys()), {"1", "5", "20"})
        self.assertEqual(rep["benchmark"], "SPY")
        self.assertTrue(rep["non_claims"])
        self.assertTrue(rep["falsifier"].strip())


class TestT2ARawBaselineUnchanged(unittest.TestCase):
    def test_raw_observed_block_is_stable(self):
        res = build_baseline_characterization(
            [A_VALIDATED, B_CONTRA, C_UNRESOLVED, D_NO_TICKERS], seed=20260608, n_sims=200)
        self.assertEqual(res["observed"]["total_scored"], 3)
        self.assertEqual(res["observed"]["any_supporting"], 1)
        self.assertEqual(res["observed"]["contradicted"], 1)
        self.assertEqual(res["observed"]["unresolved"], 1)
        self.assertEqual(res["observed"]["directional_events"], 2)


class TestHonestyContract(unittest.TestCase):
    def setUp(self):
        self.res = build_baseline_characterization([A_VALIDATED, B_CONTRA], seed=1, n_sims=200)

    def test_includes_non_claims_and_falsifier_and_limitations(self):
        self.assertTrue(self.res["non_claims"])
        self.assertIsInstance(self.res["falsifier"], str)
        self.assertTrue(self.res["falsifier"].strip())
        self.assertTrue(self.res["limitations"])

    def test_interpretation_never_asserts_below_chance(self):
        # Allowed verdicts are descriptive: above / not-above a baseline only.
        self.assertIn(self.res["interpretation"], ("above_baseline", "not_above_baseline"))

    def test_no_fdr_pool_value_fields_are_merged_in(self):
        # Separation disclaimers may MENTION the pools in string values, but no
        # data KEY may carry q-values / pool membership.
        keys = []
        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    keys.append(str(k)); walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(self.res)
        banned_key = re.compile(r"q[_-]?value|phase[_-]?[12]|\bfdr\b|benjamini|pool_member", re.I)
        leaked = [k for k in keys if banned_key.search(k)]
        self.assertEqual(leaked, [], f"FDR-pool field leaked as a key: {leaked}")

    def test_schema_version_present(self):
        self.assertEqual(self.res["schema"], "baseline_characterization.v1")


if __name__ == "__main__":
    unittest.main()
