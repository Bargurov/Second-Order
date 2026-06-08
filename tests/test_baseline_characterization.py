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
    multi_ticker_ar_observations,
    event_level_ar_status,
    build_multi_ticker_ar_characterization,
    build_multi_ticker_ar_report,
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


# ---------------------------------------------------------------------------
# T3A — multi-ticker AR-sign (all affected tickers, not only the primary)
# ---------------------------------------------------------------------------


def _ev_multi(role_specs, event_date="2026-01-01"):
    # role_specs: list of (symbol, role)
    return {"id": 1, "event_date": event_date, "mechanism_summary": "m",
            "market_tickers": [{"symbol": s, "role": r, "direction_tag": "supports"} for s, r in role_specs]}


def _fake_ar_fn(ar_by_symbol):
    """Injected AR fn: symbol -> abnormal return (same at all horizons); missing => insufficient."""
    def fn(symbol, event_date):
        key = symbol.upper()
        if key in ar_by_symbol:
            ar = ar_by_symbol[key]
            return {"status": "event_study_available", "primary_ticker": key,
                    "per_horizon": [{"horizon": h, "abnormal_return": ar} for h in (1, 5, 20)]}
        return {"status": "insufficient_data", "blocking_reasons": ["no_cached_prices_for_primary_ticker"]}
    return fn


class TestMultiTickerArMapping(unittest.TestCase):
    def test_collects_all_affected_tickers_with_ar(self):
        ev = _ev_multi([("AAA", "beneficiary"), ("BBB", "loser")])
        fn = _fake_ar_fn({"AAA": 0.02, "BBB": -0.01})  # both support
        self.assertEqual(multi_ticker_ar_observations(ev, fn, 1), [(True, True), (False, False)])

    def test_excludes_tickers_without_ar_or_with_zero_ar(self):
        ev = _ev_multi([("AAA", "beneficiary"), ("BBB", "loser"), ("CCC", "beneficiary")])
        fn = _fake_ar_fn({"AAA": 0.02, "BBB": 0.0})  # BBB zero, CCC missing
        self.assertEqual(multi_ticker_ar_observations(ev, fn, 1), [(True, True)])

    def test_excludes_non_beneficiary_loser_roles(self):
        ev = _ev_multi([("AAA", "primary"), ("BBB", "loser")])
        fn = _fake_ar_fn({"AAA": 0.02, "BBB": -0.01})
        self.assertEqual(multi_ticker_ar_observations(ev, fn, 1), [(False, False)])


class TestEventLevelArStatus(unittest.TestCase):
    def test_any_supporting_requires_at_least_one_support(self):
        self.assertEqual(event_level_ar_status([(True, False), (False, False)]), "any_supporting")  # 2nd supports

    def test_contradicted_requires_directional_tickers_but_no_support(self):
        self.assertEqual(event_level_ar_status([(True, False), (False, True)]), "contradicted")

    def test_no_observations_is_unresolved(self):
        self.assertEqual(event_level_ar_status([]), "unresolved")


class TestMultiTickerArCharacterization(unittest.TestCase):
    def _events(self, n_ben, n_los, ar):
        evs = []
        amap = {}
        for i in range(n_ben):
            sym = f"B{i}"; evs.append(_ev_multi([(sym, "beneficiary")])); amap[sym] = ar
        for i in range(n_los):
            sym = f"L{i}"; evs.append(_ev_multi([(sym, "loser")])); amap[sym] = ar
        return evs, _fake_ar_fn(amap)

    def test_mixed_roles_make_marginal_non_degenerate_and_reliable(self):
        evs, fn = self._events(12, 12, 0.01)  # a = 0.5
        res = build_multi_ticker_ar_characterization(evs, fn, horizon=1, seed=1, n_sims=200)
        self.assertGreater(res["predicted_up_fraction"], 0.0)
        self.assertLess(res["predicted_up_fraction"], 1.0)
        self.assertTrue(res["reliable"])

    def test_all_beneficiary_is_degenerate_not_reliable(self):
        evs, fn = self._events(12, 0, 0.01)  # a = 1.0
        res = build_multi_ticker_ar_characterization(evs, fn, horizon=1, seed=1, n_sims=200)
        self.assertEqual(res["predicted_up_fraction"], 1.0)
        self.assertFalse(res["reliable"])

    def test_thin_loser_minority_is_flagged_by_count(self):
        evs, fn = self._events(40, 3, 0.01)  # only 3 loser obs
        res = build_multi_ticker_ar_characterization(evs, fn, horizon=1, seed=1, n_sims=200)
        self.assertTrue(res["thin_minority"])

    def test_thin_minority_is_flagged_by_low_coverage_even_when_count_is_adequate(self):
        # 20 beneficiary events (all AR), 30 loser events but only 11 have AR ->
        # loser count 11 (>=10) yet loser coverage 11/30 = 0.37 (< 0.40) -> thin.
        evs = []
        amap = {}
        for i in range(20):
            s = f"B{i}"; evs.append(_ev_multi([(s, "beneficiary")])); amap[s] = 0.01
        for i in range(30):
            s = f"L{i}"; evs.append(_ev_multi([(s, "loser")]))
            if i < 11:
                amap[s] = -0.01  # only 11 losers have AR
        res = build_multi_ticker_ar_characterization(evs, _fake_ar_fn(amap), horizon=1, seed=1, n_sims=100)
        self.assertGreaterEqual(res["coverage"]["loser_ar"], 10)
        self.assertLess(res["coverage"]["loser_coverage"], 0.40)
        self.assertTrue(res["thin_minority"])

    def test_deterministic_with_fixed_seed(self):
        evs, fn = self._events(8, 8, 0.02)
        r1 = build_multi_ticker_ar_characterization(evs, fn, horizon=1, seed=5, n_sims=300)
        r2 = build_multi_ticker_ar_characterization(evs, fn, horizon=1, seed=5, n_sims=300)
        self.assertEqual(r1["ticker_level"], r2["ticker_level"])
        self.assertEqual(r1["event_level"], r2["event_level"])

    def test_unresolved_events_not_dropped_from_event_totals(self):
        # one event whose ticker has no AR -> unresolved, must still be counted.
        evs = [_ev_multi([("AAA", "beneficiary")]), _ev_multi([("ZZZ", "loser")])]
        fn = _fake_ar_fn({"AAA": 0.02})  # ZZZ missing
        res = build_multi_ticker_ar_characterization(evs, fn, horizon=1, seed=1, n_sims=50)
        ev = res["event_level"]
        self.assertEqual(ev["any_supporting"] + ev["contradicted"] + ev["unresolved"], res["total_events"])
        self.assertEqual(ev["unresolved"], 1)


class TestMultiTickerArReport(unittest.TestCase):
    def test_report_top_line_is_mixed_when_horizon_signs_flip(self):
        # AR positive at 1d (beneficiaries support), negative at 5d/20d -> sign flip.
        def fn(symbol, event_date):
            ar = {"1": 0.02, "5": -0.02, "20": 0.02}
            return {"status": "event_study_available", "primary_ticker": symbol.upper(),
                    "per_horizon": [{"horizon": int(h), "abnormal_return": a} for h, a in ar.items()]}
        evs = [_ev_multi([(f"B{i}", "beneficiary"), (f"L{i}", "loser")]) for i in range(12)]
        rep = build_multi_ticker_ar_report(evs, fn, seed=1, n_sims=200)
        self.assertEqual(set(rep["horizons"].keys()), {"1", "5", "20"})
        self.assertIn(rep["interpretation"], ("mixed_no_consistent_signal", "not_above_baseline", "not_reliable"))
        self.assertNotEqual(rep["interpretation"], "above_baseline")
        self.assertTrue(rep["non_claims"])
        self.assertTrue(rep["falsifier"].strip())
        self.assertIn("coverage", rep)


class TestEventStudyArForSymbolWrapper(unittest.TestCase):
    def test_delegates_with_symbol_as_primary(self):
        from event_study_validation import event_study_ar_for_symbol
        block = event_study_ar_for_symbol("ZZZZNOPE", "2026-01-01")
        self.assertEqual(block.get("primary_ticker"), "ZZZZNOPE")
        self.assertIn("status", block)


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
