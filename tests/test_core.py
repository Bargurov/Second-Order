"""Behavioral checks on synthetic data. No market/provider requests."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest
from pydantic import ValidationError
from second_order.anchors import DataUnavailable, anchors
from second_order.data import Observation, Series, Session
from second_order.evaluation import dossier_verdict, evaluate, placebo, rules_configurations, scoreboard
from second_order.registry import registry_ids, resolve, source_bound
from second_order.schema import Hypothesis, parse_output
from second_order.scoring import Rules, fit_market_model, measure, percentile_rank, score_at, verdict
from second_order.store import freeze, open_store, read_evaluations, save_evaluation

START = datetime(2020, 1, 1, 21, tzinfo=timezone.utc)
RULES = Rules(reference_days=250, min_windows=120)


def series(observable="yield:us10y", count=760, data=None, contract=None):
    data = data if data is not None else [4 + .1 * math.sin(i / 7) for i in range(count)]
    points = tuple(Observation(START + timedelta(days=i), value, contract) for i, value in enumerate(data))
    sessions = tuple(Session(point.at - timedelta(hours=6, minutes=30), point.at) for point in points)
    return Series(observable, points, "synthetic-test", "adjusted" if observable.startswith("us_") else "raw",
                  sessions=sessions)


def hypothesis(replay=True, primary="yield:us10y", at=None, frozen=None, horizon=5):
    at = at or START + timedelta(days=600, hours=-7)
    frozen = frozen or at + timedelta(minutes=10)
    value = {
        "event": {"headline": "Synthetic policy announcement", "source_url": "https://example.com/event", "published_at": at},
        "frozen_at": frozen, "replay_as_of": at if replay else None,
        "evidence_class": "replay" if replay else "prospective", "usage": "showcase", "story_id": "test-story",
        "engine": {"provider": "test", "model": "test", "prompt_hash": "a" * 64},
        "summary": "A synthetic hypothesis used only for behavioral verification.",
        "nodes": [{"id": "event", "label": "Event", "kind": "event"},
                  {"id": "primary-node", "label": "Primary observable", "kind": "observable"},
                  {"id": "secondary-node", "label": "Secondary observable", "kind": "observable"}],
        "edges": [{"source": "event", "target": "primary-node"}, {"source": "event", "target": "secondary-node"}],
        "legs": [
            {"id": "primary", "node_id": "primary-node", "primary": True, "channel": "rates_path",
             "observable_id": primary, "link": "proxy", "expected": "down", "horizon": horizon,
             "falsifier": "An unusually large opposite move.", "rationale": "Test primary.",
             "headline_reports_move": False},
            {"id": "secondary", "node_id": "secondary-node", "primary": False, "channel": "rate_differential",
             "observable_id": "index:dxy", "link": "proxy", "expected": "down", "horizon": 1,
             "falsifier": "An unusually large opposite move.", "rationale": "Test secondary.",
             "headline_reports_move": False},
        ],
    }
    return Hypothesis.model_validate(value)


def change(hyp, **updates):
    value = hyp.model_dump(mode="python")
    value.update(updates)
    return Hypothesis.model_validate(value)


def equity_pair(count=760):
    """Adjusted asset and SPY closes with a known beta and non-zero residuals."""
    market, asset = [100.0], [100.0]
    for i in range(count - 1):
        market_return = .002 * math.sin(i / 3)
        market.append(market[-1] * (1 + market_return))
        asset.append(asset[-1] * (1 + .0002 + 1.5 * market_return + .004 * math.sin(i * 1.7)))
    return series("us_equity:MSFT", data=asset), series("us_etf:SPY", data=market)


def with_values(data, changes):
    return replace(data, observations=tuple(replace(p, value=changes.get(i, p.value))
                                            for i, p in enumerate(data.observations)))


def late_equity_hypothesis():
    # Published during session 600 (event anchor 599); frozen after the close of session 614,
    # fifteen sessions later, so the out-of-session freeze scores from close 614.
    return hypothesis(False, "us_equity:MSFT", START + timedelta(days=600, hours=-3),
                      START + timedelta(days=614, hours=2), horizon=1)


class SchemaTests(unittest.TestCase):
    def test_schema_is_exportable_and_json_roundtrips(self):
        hyp = hypothesis()
        self.assertEqual(parse_output(hyp.model_dump_json()), hyp)
        self.assertFalse(Hypothesis.model_json_schema()["additionalProperties"])

    def test_malformed_output_fails_without_json_extraction(self):
        with self.assertRaises(ValidationError):
            parse_output("Here is JSON: " + hypothesis().model_dump_json())

    def test_frozen_nested_models_and_tuples(self):
        hyp = hypothesis()
        with self.assertRaises(ValidationError):
            hyp.summary = "Changed"
        with self.assertRaises(ValidationError):
            hyp.legs[0].expected = "up"
        self.assertIsInstance(hyp.legs, tuple)

    def test_one_primary_required(self):
        value = hypothesis().model_dump()
        value["legs"][1]["primary"] = True
        with self.assertRaises(ValidationError):
            Hypothesis.model_validate(value)

    def test_timezone_and_replay_clock_are_required(self):
        value = hypothesis().model_dump()
        value["event"]["published_at"] = datetime(2024, 1, 1)
        with self.assertRaises(ValidationError):
            Hypothesis.model_validate(value)
        value = hypothesis().model_dump()
        value["replay_as_of"] = None
        with self.assertRaises(ValidationError):
            Hypothesis.model_validate(value)

    def test_free_form_expression_and_unknown_fields_rejected(self):
        value = hypothesis().model_dump()
        value["legs"][0]["observable_id"] = "RB=F*42-BZ=F"
        with self.assertRaises(ValidationError):
            Hypothesis.model_validate(value)
        value = hypothesis().model_dump()
        value["verdict"] = "supported"
        with self.assertRaises(ValidationError):
            Hypothesis.model_validate(value)

    def test_headline_reports_move_is_required_and_not_nullable(self):
        for name, mutate in (("missing", lambda leg: leg.pop("headline_reports_move")),
                             ("null", lambda leg: leg.update(headline_reports_move=None))):
            with self.subTest(name):
                value = hypothesis().model_dump(mode="json")
                mutate(value["legs"][0])
                with self.assertRaises(ValidationError):
                    parse_output(json.dumps(value))
        leg_schema = Hypothesis.model_json_schema()["$defs"]["Leg"]
        self.assertIn("headline_reports_move", leg_schema["required"])
        self.assertNotIn("default", leg_schema["properties"]["headline_reports_move"])

    def test_cycle_and_reused_observable_rejected(self):
        value = hypothesis().model_dump()
        value["edges"] = value["edges"] + ({"source": "primary-node", "target": "event"},)
        with self.assertRaises(ValidationError):
            Hypothesis.model_validate(value)
        value = hypothesis().model_dump()
        value["legs"][1]["observable_id"] = value["legs"][0]["observable_id"]
        with self.assertRaises(ValidationError):
            Hypothesis.model_validate(value)


class AnchorTests(unittest.TestCase):
    # Synthetic sessions run 14:30-21:00 UTC and close at observations[i].at.
    def test_intraday_equity_freeze_starts_at_next_close(self):
        data = series("us_etf:XLE", 10)
        at = data.observations[4].at - timedelta(hours=5)
        hyp = hypothesis(False, "us_etf:XLE", at, at + timedelta(hours=1))
        result = anchors(hyp, data)
        self.assertEqual((result.event_index, result.score_index, result.reference_end), (3, 4, 3))
        self.assertEqual(result.reason, "regular_session_first_close_after_freeze")

    def test_overnight_freeze_uses_last_close_before_freeze(self):
        data = series("us_etf:XLE", 10)
        at = data.observations[4].at + timedelta(hours=1)
        result = anchors(hypothesis(False, "us_etf:XLE", at, at + timedelta(hours=1)), data)
        self.assertEqual((result.event_index, result.score_index, result.reference_end), (4, 4, 4))
        self.assertEqual(result.reason, "regular_session_last_close_before_freeze")

    def test_daytime_news_evening_freeze_scores_from_that_sessions_close(self):
        data = series("us_etf:XLE", 10)
        at = data.observations[4].at - timedelta(hours=3)
        result = anchors(hypothesis(False, "us_etf:XLE", at, data.observations[4].at + timedelta(hours=3)), data)
        # The session seen before the freeze stays unscored; its close anchors the scored window.
        self.assertEqual((result.event_index, result.score_index, result.reference_end), (3, 4, 3))
        self.assertEqual(result.reason, "regular_session_last_close_before_freeze")

    def test_premarket_news_evening_freeze_scores_from_last_close(self):
        data = series("us_etf:XLE", 10)
        at = data.observations[4].at - timedelta(hours=10)
        result = anchors(hypothesis(False, "us_etf:XLE", at, at + timedelta(hours=12)), data)
        self.assertEqual((result.event_index, result.score_index, result.reference_end), (3, 4, 3))

    def test_freeze_at_the_close_waits_for_the_next_close(self):
        data = series("us_etf:XLE", 10)
        at = data.observations[4].at - timedelta(hours=3)
        result = anchors(hypothesis(False, "us_etf:XLE", at, data.observations[4].at), data)
        self.assertEqual(result.score_index, 5)
        self.assertEqual(result.reason, "regular_session_first_close_after_freeze")

    def test_missing_bar_at_the_anchoring_close_is_unavailable(self):
        data = series("us_etf:XLE", 10)
        at = data.observations[4].at - timedelta(hours=3)
        frozen = data.observations[4].at + timedelta(hours=3)
        gapped = replace(data, observations=data.observations[:4] + data.observations[5:])
        with self.assertRaises(DataUnavailable):
            anchors(hypothesis(False, "us_etf:XLE", at, frozen), gapped)

    def test_futures_always_use_next_observation(self):
        data = series("futures:wti", 10, [70.0] * 10, "CL-2025-01")
        at = data.observations[4].at + timedelta(hours=1)
        result = anchors(hypothesis(False, "futures:wti", at, at + timedelta(hours=1)), data)
        self.assertEqual(result.score_index, 5)
        self.assertEqual(result.reason, "first_post_freeze_observation")
        at = data.observations[4].at - timedelta(hours=3)
        result = anchors(hypothesis(False, "futures:wti", at, data.observations[4].at + timedelta(hours=3)), data)
        self.assertEqual(result.score_index, 5)

    def test_replay_has_explicit_publication_anchor(self):
        data = series(count=10)
        at = data.observations[4].at - timedelta(hours=5)
        result = anchors(hypothesis(True, at=at, frozen=at + timedelta(days=20)), data)
        self.assertEqual((result.event_index, result.score_index), (3, 3))

    def test_overnight_freeze_requires_calendar_coverage(self):
        data = series("us_etf:XLE", 10)
        data = replace(data, sessions=data.sessions[:5])
        at = data.observations[4].at + timedelta(hours=1)
        with self.assertRaises(DataUnavailable):
            anchors(hypothesis(False, "us_etf:XLE", at, at + timedelta(hours=1)), data)

    def test_holiday_gap_uses_supplied_sessions(self):
        times = [datetime(2024, 11, day, 21, tzinfo=timezone.utc) for day in (26, 27, 29)]
        # A supplied holiday/early-close calendar; no Thursday observation is invented.
        times[-1] = times[-1].replace(hour=18)
        data = Series("us_etf:XLE", tuple(Observation(at, 100) for at in times), "test", "adjusted",
                      sessions=tuple(Session(at.replace(hour=14, minute=30), at) for at in times))
        at = datetime(2024, 11, 28, 10, tzinfo=timezone.utc)
        result = anchors(hypothesis(False, "us_etf:XLE", at, at + timedelta(hours=1)), data)
        self.assertEqual(result.score_index, 1)

    def test_unverified_daily_timestamp_cannot_support_equity_anchor(self):
        data = replace(series("us_etf:XLE", 10), timestamp_basis="date_end_convention")
        at = data.observations[4].at + timedelta(hours=1)
        with self.assertRaises(DataUnavailable):
            anchors(hypothesis(False, "us_etf:XLE", at, at + timedelta(hours=1)), data)


class ScoringTests(unittest.TestCase):
    def test_trend_counterexample_does_not_support_wrong_direction(self):
        data = [10 - .01 * i for i in range(300)]
        data[201] = data[200] - .002
        result = score_at(series(data=data), resolve("yield:us10y"), 200, 200, 1, "up", RULES)
        self.assertGreaterEqual(result.percentile_rank, .8)
        self.assertLess(result.signed_move, 0)
        self.assertEqual(result.verdict, "inconclusive")

    def test_ties_and_zero_change(self):
        self.assertEqual(percentile_rank(2, [1, 2, 2, 3]), .5)
        self.assertEqual(percentile_rank(0, [0] * 250), .5)
        self.assertEqual(verdict(0, 1, RULES), "inconclusive")

    def test_all_numeric_verdicts_and_boundaries(self):
        for move, rank, expected in [(1, .8, "supported"), (-1, .2, "contradicted"),
                                     (1, .5, "inconclusive"), (-1, .9, "inconclusive")]:
            with self.subTest(move=move, rank=rank):
                self.assertEqual(verdict(move, rank, RULES), expected)
        with self.assertRaises(ValueError):
            verdict(float("nan"), .5, RULES)

    def test_opposite_predictions_transform_reference_too(self):
        data = series()
        up = score_at(data, resolve(data.observable_id), 600, 600, 5, "up", RULES)
        down = score_at(data, resolve(data.observable_id), 600, 600, 5, "down", RULES)
        self.assertAlmostEqual(up.percentile_rank + down.percentile_rank, 1)
        self.assertAlmostEqual(up.signed_move, -down.signed_move)

    def test_120_windows_is_an_availability_gate(self):
        result = score_at(series(count=100), resolve("yield:us10y"), 80, 80, 5, "down", RULES)
        self.assertEqual(result.verdict, "unavailable")

    def test_20_day_overlap_is_not_reported_as_independent_n(self):
        result = score_at(series(), resolve("yield:us10y"), 600, 600, 20, "down", RULES)
        self.assertEqual(result.reference_windows, 231)
        self.assertEqual(result.non_overlapping_reference_windows, 12)

    def test_registry_units_and_contract_policy(self):
        expected = {
            "yield:us2y": (4, 4.1, 10), "yield:us10y": (4, 4.1, 10),
            "index:dxy": (100, 102, 2), "fx:usdils": (3.5, 3.57, 2),
            "futures:wti": (70, 71.4, 2), "futures:brent": (75, 76.5, 2),
            "yield:ust2y_cmt": (4, 4.1, 10), "yield:ust10y_cmt": (4, 4.1, 10),
        }
        for name, (first, last, target) in expected.items():
            with self.subTest(name=name):
                data = series(name, 2, [first, last], "verified-contract")
                self.assertAlmostEqual(measure(data, resolve(name), 0, 1), target)
        self.assertEqual(len(registry_ids()), 12)
        # Source-bound IDs are distinct from the fixture concept IDs the showcases use, and each provider's are its own:
        # the FRED IDs keep their meaning, and the Board's H.15 package has separate IDs.
        self.assertEqual(source_bound("fred"), {"yield:ust2y_cmt": "DGS2", "yield:ust10y_cmt": "DGS10"})
        self.assertEqual(source_bound("board-h15"), {"yield:ust2y_cmt_h15": "RIFLGFCY02_N.B",
                                                     "yield:ust10y_cmt_h15": "RIFLGFCY10_N.B"})
        with self.assertRaises(ValueError):
            source_bound("unknown")
        self.assertIsNone(resolve("yield:us10y").source)
        for name in ("us_equity:MSFT", "us_etf:XLE"):
            self.assertEqual(resolve(name).benchmark, "us_etf:SPY")
        with self.assertRaises(ValueError):
            resolve("us_equity:MSFT;DROP TABLE")

    def test_futures_missing_contract_and_roll_are_unavailable(self):
        data = series("futures:wti", 300, [70 + .01 * i for i in range(300)])
        result = score_at(data, resolve(data.observable_id), 250, 250, 5, "up", RULES)
        self.assertEqual(result.verdict, "unavailable")
        data = replace(data, observations=tuple(replace(p, contract="A" if i <= 252 else "B")
                                               for i, p in enumerate(data.observations)))
        result = score_at(data, resolve(data.observable_id), 250, 250, 5, "up", RULES)
        self.assertEqual(result.verdict, "unavailable")

    def test_new_market_model_estimates_alpha_and_beta(self):
        market_returns = [.002 * math.sin(i / 3) for i in range(760)]
        asset_prices, market_prices = [100.0], [100.0]
        for i, market_return in enumerate(market_returns):
            market_prices.append(market_prices[-1] * (1 + market_return))
            extra = .01 if i == 600 else 0
            asset_prices.append(asset_prices[-1] * (1 + .0002 + 1.5 * market_return + extra))
        asset = series("us_equity:MSFT", data=asset_prices)
        benchmark = series("us_etf:SPY", data=market_prices)
        model = fit_market_model(asset, benchmark, 600, RULES)
        self.assertAlmostEqual(model.alpha, .0002, places=10)
        self.assertAlmostEqual(model.beta, 1.5, places=10)
        self.assertAlmostEqual(measure(asset, resolve(asset.observable_id), 600, 1, model, benchmark), 1, places=8)

    def test_model_rejects_raw_basis_and_a_fit_beyond_the_freeze(self):
        asset, benchmark = series("us_equity:MSFT"), series("us_etf:SPY")
        result = score_at(replace(asset, basis="raw"), resolve(asset.observable_id),
                          600, 600, 1, "up", RULES, benchmark)
        self.assertEqual(result.verdict, "unavailable")
        # Defence in depth: a fit ending after the last observation known at freeze is refused.
        result = score_at(asset, resolve(asset.observable_id), 600, 599, 1, "up",
                          replace(RULES, estimation_gap=0), benchmark, available_end=599, estimation_anchor=600)
        self.assertEqual(result.verdict, "unavailable")

    def test_stationary_continuous_simulation_only(self):
        rng = random.Random(99)
        reference = [rng.gauss(0, 1) for _ in range(2000)]
        counts = {"supported": 0, "contradicted": 0, "inconclusive": 0}
        for _ in range(4000):
            move = rng.gauss(0, 1)
            counts[verdict(move, percentile_rank(move, reference), RULES)] += 1
        self.assertAlmostEqual(counts["supported"] / 4000, .2, delta=.04)
        self.assertAlmostEqual(counts["contradicted"] / 4000, .2, delta=.04)


class EvaluationTests(unittest.TestCase):
    def test_missing_primary_is_unavailable_without_crash(self):
        result = evaluate(hypothesis(), {}, START + timedelta(days=700))
        self.assertEqual(result["verdict"], "unavailable")

    def test_pending_uses_explicit_clock(self):
        hyp = hypothesis()
        result = evaluate(hyp, {"yield:us10y": series()}, hyp.effective_freeze)
        self.assertEqual(result["legs"][0]["verdict"], "pending")

    def test_missing_bar_does_not_compress_horizon(self):
        hyp, data = hypothesis(horizon=1), series()
        points = list(data.observations)
        points[600] = replace(points[600], value=None)
        data = replace(data, observations=tuple(points))
        result = evaluate(hyp, {data.observable_id: data}, START + timedelta(days=700))
        self.assertEqual(result["legs"][0]["target_at"], points[600].at.isoformat())
        self.assertEqual(result["legs"][0]["verdict"], "unavailable")

    def test_reported_move_excluded_only_when_anchor_matches(self):
        hyp = hypothesis()
        value = hyp.model_dump()
        value["legs"][0]["headline_reports_move"] = True
        replay = Hypothesis.model_validate(value)
        data = {"yield:us10y": series()}
        self.assertEqual(evaluate(replay, data, START + timedelta(days=700))["legs"][0]["verdict"], "excluded")
        prospective = change(replay, evidence_class="prospective", replay_as_of=None)
        self.assertNotEqual(evaluate(prospective, data, START + timedelta(days=700))["legs"][0]["verdict"], "excluded")

    def test_unverified_timestamp_is_not_research_evidence(self):
        hyp = change(hypothesis(), usage="research")
        data = replace(series(), timestamp_basis="date_end_convention")
        result = evaluate(hyp, {data.observable_id: data}, START + timedelta(days=700))
        self.assertEqual(result["verdict"], "unavailable")

    def test_initial_reaction_cannot_enter_event_reference_windows(self):
        # Prospective freeze five observations after publication: event anchor 599, score anchor 605.
        published = START + timedelta(days=600, hours=-7)
        hyp = hypothesis(False, at=published, frozen=published + timedelta(days=5))
        calm = series()
        spiked = series(data=[p.value + (5.0 if 600 <= i <= 604 else 0.0)
                              for i, p in enumerate(calm.observations)])
        as_of = START + timedelta(days=700)
        calm_leg = evaluate(hyp, {"yield:us10y": calm}, as_of)["legs"][0]
        spiked_leg = evaluate(hyp, {"yield:us10y": spiked}, as_of)["legs"][0]
        self.assertEqual(calm_leg["event_anchor"], calm.observations[599].at.isoformat())
        self.assertEqual(calm_leg["reference_end"], calm.observations[599].at.isoformat())
        self.assertEqual(calm_leg["score_anchor"], calm.observations[605].at.isoformat())
        # The unscored reaction (600-604) changes neither the scored move nor its ordinary history.
        for key in ("measured_change", "percentile_rank", "reference_windows", "verdict", "placebo"):
            with self.subTest(key=key):
                self.assertEqual(spiked_leg[key], calm_leg[key])

    def test_late_freeze_fit_ignores_unscored_post_publication_prices(self):
        asset, spy = equity_pair()
        hyp, as_of = late_equity_hypothesis(), START + timedelta(days=700)
        calm = evaluate(hyp, {"us_equity:MSFT": asset, "us_etf:SPY": spy}, as_of)["legs"][0]
        # Only observations strictly between publication and the score anchor change (600-613);
        # the score anchor (614) and horizon endpoint (615) prices are held fixed.
        shocked_asset = with_values(asset, {i: asset.observations[i].value * 1.25 for i in range(600, 614)})
        shocked_spy = with_values(spy, {i: spy.observations[i].value * 0.9 for i in range(600, 614)})
        shocked = evaluate(hyp, {"us_equity:MSFT": shocked_asset, "us_etf:SPY": shocked_spy}, as_of)["legs"][0]
        self.assertEqual(calm["anchor_policy"], "regular_session_last_close_before_freeze")
        self.assertEqual((calm["event_anchor"], calm["score_anchor"]),
                         (asset.observations[599].at.isoformat(), asset.observations[614].at.isoformat()))
        self.assertIsNotNone(calm["percentile_rank"])
        window = calm["estimation_window"]
        self.assertEqual((window["first_price_at"], window["last_price_at"], window["returns"]),
                         (asset.observations[339].at.isoformat(), asset.observations[589].at.isoformat(), 250))
        for key in ("estimation_window", "measured_change", "signed_move", "percentile_rank", "verdict", "placebo"):
            with self.subTest(key=key):
                self.assertEqual(shocked[key], calm[key])
        # The shock is material: a fit anchored at the score anchor would have moved.
        self.assertNotEqual(fit_market_model(asset, spy, 614, RULES), fit_market_model(shocked_asset, shocked_spy, 614, RULES))

    def test_scored_endpoint_prices_may_change_the_result(self):
        asset, spy = equity_pair()
        hyp, as_of = late_equity_hypothesis(), START + timedelta(days=700)
        calm = evaluate(hyp, {"us_equity:MSFT": asset, "us_etf:SPY": spy}, as_of)["legs"][0]
        moved_asset = with_values(asset, {615: asset.observations[615].value * 1.03})
        moved = evaluate(hyp, {"us_equity:MSFT": moved_asset, "us_etf:SPY": spy}, as_of)["legs"][0]
        self.assertEqual(moved["estimation_window"], calm["estimation_window"])
        self.assertNotEqual(moved["measured_change"], calm["measured_change"])

    def test_missing_pre_event_history_is_unavailable_not_substituted(self):
        asset, spy = equity_pair(400)
        # Event anchor 255 needs prices from index -5; the late score anchor (270) would not.
        hyp = hypothesis(False, "us_equity:MSFT", START + timedelta(days=256, hours=-3),
                         START + timedelta(days=270, hours=2), horizon=1)
        leg = evaluate(hyp, {"us_equity:MSFT": asset, "us_etf:SPY": spy}, START + timedelta(days=300))["legs"][0]
        self.assertEqual(leg["score_anchor"], asset.observations[270].at.isoformat())
        self.assertEqual(leg["verdict"], "unavailable")
        self.assertIn("pre-event", leg["reason"])
        self.assertNotIn("estimation_window", leg)
        fit_market_model(asset, spy, 270, RULES)  # Post-publication history exists but is not substituted.

    def test_replay_fit_is_unchanged_and_only_equity_legs_record_a_fit(self):
        asset, spy = equity_pair()
        replay = hypothesis(True, "us_equity:MSFT", START + timedelta(days=600, hours=-3), horizon=1)
        leg = evaluate(replay, {"us_equity:MSFT": asset, "us_etf:SPY": spy}, START + timedelta(days=700))["legs"][0]
        self.assertEqual(leg["score_anchor"], leg["event_anchor"])
        self.assertEqual(leg["estimation_window"]["last_price_at"], asset.observations[589].at.isoformat())
        model = fit_market_model(asset, spy, 599, RULES)
        self.assertEqual((leg["estimation_window"]["alpha"], leg["estimation_window"]["beta"]), (model.alpha, model.beta))
        yields = evaluate(hypothesis(), {"yield:us10y": series()}, START + timedelta(days=700))["legs"][0]
        self.assertNotIn("estimation_window", yields)

    def test_placebo_is_deterministic_and_future_outcomes_do_not_change_it(self):
        data, hyp = series(), hypothesis()
        first = placebo(data, hyp.legs[0], 599, 599, RULES)
        self.assertEqual(first["selected"], 50)
        last_control = datetime.fromisoformat(first["selected_dates"][-1])
        self.assertLess(last_control + timedelta(days=5), data.observations[599].at)
        points = tuple(replace(p, value=99.0) if i >= 600 else p for i, p in enumerate(data.observations))
        second = placebo(replace(data, observations=points), hyp.legs[0], 599, 599, RULES)
        self.assertEqual(first, second)

    def test_mixed_incomplete_and_primary_dossier_states(self):
        self.assertEqual(dossier_verdict([{"primary": True, "verdict": "supported"},
                                         {"primary": False, "verdict": "contradicted"}]), "mixed")
        self.assertEqual(dossier_verdict([{"primary": True, "verdict": "supported"},
                                         {"primary": False, "verdict": "pending"}]), "incomplete")
        self.assertEqual(dossier_verdict([{"primary": True, "verdict": "contradicted"},
                                         {"primary": False, "verdict": "supported"}]), "contradicted")

    def test_showcase_exclusion_class_separation_and_duplicate_evaluations(self):
        row = evaluate(hypothesis(), {"yield:us10y": series()}, START + timedelta(days=700))
        selected = row["rules_hash"]
        self.assertEqual(scoreboard([row], "replay", selected)["hypotheses"], 0)
        research = {**row, "usage": "research"}
        summary = scoreboard([research, research], "replay", selected)
        self.assertEqual(summary["hypotheses"], 1)
        self.assertEqual(summary["story_groups"], 1)
        self.assertEqual(scoreboard([research], "prospective", selected)["hypotheses"], 0)
        with self.assertRaises(ValueError):
            scoreboard([research], "all", selected)

    def test_revisions_do_not_improve_scoreboard(self):
        row = evaluate(hypothesis(), {"yield:us10y": series()}, START + timedelta(days=700))
        research = {**row, "usage": "research", "supersedes": "old"}
        self.assertEqual(scoreboard([research], "replay", row["rules_hash"])["hypotheses"], 0)

    def test_scoreboard_selects_exactly_one_rules_configuration(self):
        data = {"yield:us10y": series()}
        first, second = hypothesis(), hypothesis(at=START + timedelta(days=620, hours=-7))
        current, older = Rules(), replace(RULES, version="0.3.0")
        rows = [{**evaluate(hyp, data, START + timedelta(days=days), rules), "usage": "research"}
                for hyp, days, rules in ((first, 700, current), (second, 700, current), (first, 650, older))]
        configurations = rules_configurations(rows)
        self.assertEqual([(c["rules_version"], c["evaluations"], c["hypotheses"]) for c in configurations],
                         [("0.3.0", 1, 1), (current.version, 2, 2)])
        newest = scoreboard(rows, "replay", current.hash)
        self.assertEqual((newest["rules_version"], newest["rules_hash"], newest["hypotheses"]),
                         (current.version, current.hash, 2))
        # The older configuration uses its own (earlier) evaluation, not the later current one.
        earlier = scoreboard(rows, "replay", older.hash)
        self.assertEqual((earlier["rules_version"], earlier["hypotheses"]), ("0.3.0", 1))
        unknown = scoreboard(rows, "replay", "0" * 64)
        self.assertEqual((unknown["rules_version"], unknown["hypotheses"], unknown["rates"]["supported"]),
                         (None, 0, None))
        for invalid in ("", "different", current.hash.upper(), None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                scoreboard(rows, "replay", invalid)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.connection = open_store()

    def tearDown(self):
        self.connection.close()

    def test_freeze_and_evaluation_are_idempotent_and_append_only(self):
        hyp = hypothesis()
        now = START + timedelta(days=800)
        identity = freeze(self.connection, hyp, now)
        self.assertEqual(freeze(self.connection, hyp, now), identity)
        row = evaluate(hyp, {"yield:us10y": series()}, START + timedelta(days=700))
        eval_id = save_evaluation(self.connection, identity, row, now)
        self.assertEqual(save_evaluation(self.connection, identity, row, now), eval_id)
        for table in ("hypotheses", "evaluations"):
            with self.subTest(table=table):
                self.assertEqual(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 1)
                with self.assertRaises(sqlite3.IntegrityError):
                    self.connection.execute(f"DELETE FROM {table}")
                with self.assertRaises(sqlite3.IntegrityError):
                    self.connection.execute(f"UPDATE {table} SET payload='changed'")

    def test_prospective_freeze_cannot_be_backdated(self):
        hyp = hypothesis(False)
        with self.assertRaises(ValueError):
            freeze(self.connection, hyp, hyp.frozen_at + timedelta(days=10))
        self.assertTrue(freeze(self.connection, hyp, hyp.frozen_at))

    def test_version_and_rule_change_append_new_rows(self):
        hyp, now = hypothesis(), START + timedelta(days=800)
        first = freeze(self.connection, hyp, now)
        newer = change(hyp, frozen_at=hyp.frozen_at + timedelta(days=1), supersedes=first, summary="New version.")
        second = freeze(self.connection, newer, now)
        self.assertNotEqual(first, second)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM hypotheses").fetchone()[0], 2)
        data = {"yield:us10y": series()}
        old = evaluate(hyp, data, START + timedelta(days=700), RULES)
        revised = evaluate(hyp, data, START + timedelta(days=700), replace(RULES, version="0.2.1", upper=.9))
        self.assertNotEqual(save_evaluation(self.connection, first, old, now),
                            save_evaluation(self.connection, first, revised, now))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0], 2)

    def test_request_hash_includes_event_date(self):
        hyp, now = hypothesis(), START + timedelta(days=800)
        freeze(self.connection, hyp, now)
        event = hyp.event.model_copy(update={"published_at": hyp.event.published_at + timedelta(days=1)})
        newer = change(hyp, event=event, frozen_at=hyp.frozen_at + timedelta(days=1), replay_as_of=event.published_at)
        freeze(self.connection, newer, now)
        hashes = [row[0] for row in self.connection.execute("SELECT request_hash FROM hypotheses")]
        self.assertEqual(len(set(hashes)), 2)

    def test_evaluation_identity_and_clock_are_checked(self):
        hyp, now = hypothesis(), START + timedelta(days=800)
        identity = freeze(self.connection, hyp, now)
        row = evaluate(hyp, {"yield:us10y": series()}, START + timedelta(days=700))
        with self.assertRaises(ValueError):
            save_evaluation(self.connection, "another-hypothesis", row, now)
        with self.assertRaises(ValueError):
            save_evaluation(self.connection, identity, row, START + timedelta(days=650))


def snapshot(folder: Path) -> dict:
    """Name -> (sha256, size, mtime) for every file, so reads can be proven write-free."""
    return {path.name: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size, path.stat().st_mtime_ns)
            for path in sorted(folder.iterdir())}


class ReadOnlyStoreTests(unittest.TestCase):
    def test_reader_returns_every_configuration_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "store.db"
            connection = open_store(str(path))
            hyp, now = hypothesis(), START + timedelta(days=800)
            identity = freeze(connection, hyp, now)
            for rules in (Rules(), replace(RULES, version="0.3.0")):
                save_evaluation(connection, identity, evaluate(hyp, {"yield:us10y": series()},
                                                               START + timedelta(days=700), rules), now)
            connection.close()
            before = snapshot(Path(folder))
            rows = read_evaluations(str(path))
            self.assertEqual(snapshot(Path(folder)), before)  # Same bytes, size and mtime; no sidecars.
            self.assertEqual(len(rows), 2)
            self.assertEqual([c["rules_version"] for c in rules_configurations(rows)], ["0.3.0", Rules().version])

    def test_reader_refuses_missing_and_foreign_databases_without_creating_them(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                read_evaluations(str(Path(folder) / "missing.db"))
            self.assertEqual(list(Path(folder).iterdir()), [])
            foreign = Path(folder) / "v1.db"
            connection = sqlite3.connect(foreign)
            connection.execute("CREATE TABLE events(id INTEGER)")
            connection.commit()
            connection.close()
            before = snapshot(Path(folder))
            with self.assertRaises(ValueError):
                read_evaluations(str(foreign))
            self.assertEqual(snapshot(Path(folder)), before)


if __name__ == "__main__":
    unittest.main()
