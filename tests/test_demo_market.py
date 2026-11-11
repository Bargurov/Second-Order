"""The FICTIONAL demonstration series of the offline demo and the guards that keep them out of research.

Every series value here is invented by second_order/demo_market.py; the hypotheses are SYNTHETIC or the two fictional
showcase cases. Nothing reaches a network.
"""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pydantic import ValidationError
from second_order import demo_market
from second_order.demo import DEMO_MARKET, demo_only, load_market, load_showcases, run_demo
from second_order.evaluation import scoreboard
from second_order.registry import PROVIDERS, binding, is_demo, registry_ids, resolve, source_bound
from second_order.schema import Hypothesis
from second_order.scoring import Rules
from second_order.store import freeze, open_store
from test_core import hypothesis as synthetic_hypothesis

ROOT = Path(__file__).resolve().parent.parent
DEMO_IDS = ("demo:rate", "demo:fx-index")


def demo_case(usage: str = "showcase", secondary: str = "demo:fx-index") -> dict:
    """The first fictional showcase case as JSON, with the usage and the secondary leg's observable changed."""
    payload = load_showcases()[0].model_dump(mode="json")
    payload["usage"] = usage
    payload["legs"][1]["observable_id"] = secondary
    return payload


class GeneratorTests(unittest.TestCase):
    def test_the_committed_fixture_is_the_generator_output_byte_for_byte(self):
        # .gitattributes checks it out with LF on every platform, the bytes text() writes.
        self.assertEqual(DEMO_MARKET.read_bytes(), demo_market.text().encode("utf-8"))
        self.assertEqual(demo_market.build(), demo_market.build())

    def test_the_fixture_is_marked_fictional_and_names_no_capture(self):
        payload = json.loads(DEMO_MARKET.read_text(encoding="utf-8"))
        self.assertEqual((payload["version"], payload["generator"]), ("demo-market-0.1", "second_order/demo_market.py"))
        self.assertTrue(payload["description"].startswith(
            "FICTIONAL demonstration series: every number is invented by second_order/demo_market.py; nothing here is "
            "a market observation."))
        self.assertNotEqual(payload["timestamp_basis"], "observed")  # The research timestamp gate always applies.
        self.assertEqual({key: (row["provider"], row["ticker"], row["price_basis"])
                          for key, row in payload["rows"].items()},
                         {"demo:rate": ("fictional-demo", "DEMO-RATE", "fictional"),
                          "demo:fx-index": ("fictional-demo", "DEMO-FX", "fictional")})
        for key in ("captured_at", "source_commit", "source_url", "data_vintage"):
            self.assertNotIn(key, payload)
        self.assertIn("Every number this module produces is invented", demo_market.__doc__)

    def test_business_days_and_ranges(self):
        payload = demo_market.build()
        for key, (low, high) in {"demo:rate": (2.5, 5.5), "demo:fx-index": (90, 110)}.items():
            rows = payload["rows"][key]["rows"]
            days = [date.fromisoformat(day) for day, _ in rows]
            with self.subTest(series=key):
                self.assertEqual((days[0], days[-1], len(days)), (date(2022, 1, 3), date(2024, 12, 31), 782))
                self.assertTrue(all(day.weekday() < 5 for day in days))
                self.assertEqual(days, sorted(set(days)))
                self.assertTrue(all(low <= value <= high for _, value in rows))
                self.assertTrue(all(round(value, 3) == value for _, value in rows))

    def test_the_rate_falls_after_the_first_event_and_rises_after_the_second(self):
        rate = dict(map(tuple, demo_market.build()["rows"]["demo:rate"]["rows"]))
        self.assertLess((rate["2024-06-18"] - rate["2024-06-11"]) * 100, -40)  # Basis points over five sessions.
        self.assertGreater((rate["2024-11-05"] - rate["2024-10-29"]) * 100, 30)


class RegistryTests(unittest.TestCase):
    def test_demo_ids_resolve_but_stay_out_of_the_registry_and_every_provider(self):
        self.assertEqual([(resolve(key).unit, resolve(key).measurement, resolve(key).anchor_policy, resolve(key).source)
                          for key in DEMO_IDS],
                         [("bp", "yield_bp", "next_observation", None), ("%", "return_pct", "next_observation", None)])
        self.assertTrue(all(is_demo(key) and binding(key) is None for key in DEMO_IDS))
        self.assertFalse(set(DEMO_IDS) & set(registry_ids()))
        for provider in PROVIDERS:
            self.assertFalse(set(DEMO_IDS) & set(source_bound(provider)))
        self.assertFalse(any(is_demo(key) for key in ("yield:us10y", "index:dxy", "yield:ust10y_cmt_h15", "demo:x")))
        self.assertEqual((resolve("yield:us10y").unit, resolve("index:dxy").measurement), ("bp", "return_pct"))


class GuardTests(unittest.TestCase):
    def test_a_research_hypothesis_cannot_name_a_demo_series(self):
        self.assertIsInstance(Hypothesis.model_validate(demo_case()), Hypothesis)  # A demo showcase is valid.
        for secondary in ("demo:fx-index", "index:dxy"):  # Any one demo leg is enough.
            with self.subTest(secondary=secondary), \
                    self.assertRaisesRegex(ValidationError, "research hypothesis cannot name a fictional demonstration"):
                Hypothesis.model_validate(demo_case("research", secondary))

    def test_the_research_scoreboard_ignores_any_hypothesis_with_a_demo_leg(self):
        rules = Rules().hash
        relabelled = [{**row, "usage": "research"} for row in run_demo()["dossiers"]]  # As if a record said research.
        for kind in ("replay", "prospective"):
            self.assertEqual(scoreboard(relabelled, kind, rules)["hypotheses"], 0)
        mixed = json.loads(json.dumps(relabelled[0]))
        mixed["legs"][1]["observable_id"] = "index:dxy"
        self.assertEqual(scoreboard([mixed], "replay", rules)["hypotheses"], 0)
        concept = json.loads(json.dumps(mixed))
        concept["legs"][0]["observable_id"] = "yield:us10y"
        self.assertEqual(scoreboard([concept], "replay", rules)["hypotheses"], 1)  # The guard is the demo leg only.

    def test_demo_only_needs_every_leg_on_a_demo_series(self):
        self.assertTrue(all(demo_only(case) for case in load_showcases()))
        self.assertFalse(demo_only(Hypothesis.model_validate(demo_case(secondary="index:dxy"))))
        self.assertFalse(demo_only(synthetic_hypothesis()))
        self.assertEqual(set(load_market()), set(DEMO_IDS))

    def test_evaluate_scores_only_demo_hypotheses_and_skips_every_other_unbound_one(self):
        demo = load_showcases()[0]
        mixed = Hypothesis.model_validate(demo_case(secondary="index:dxy"))
        concept = synthetic_hypothesis()  # SYNTHETIC replay on the concept IDs yield:us10y and index:dxy.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "store.db"
            connection = open_store(str(path))
            recorded = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
            identities = [freeze(connection, case, recorded + timedelta(seconds=i))
                          for i, case in enumerate((demo, mixed, concept))]
            connection.close()
            run = subprocess.run([sys.executable, "-m", "second_order", "evaluate", "--db", str(path),
                                  "--as-of", "2025-01-02T00:00:00+00:00"],
                                 cwd=ROOT, text=True, capture_output=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            printed = {row["hypothesis_id"]: row for row in json.loads(run.stdout)}
            self.assertEqual(set(printed), set(identities))
            self.assertEqual(printed[identities[0]]["verdict"], "supported")
            for identity in identities[1:]:
                self.assertIn("not every leg is a fictional demonstration series", printed[identity]["skipped"])
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("SELECT hypothesis_id FROM evaluations").fetchall(),
                                 [(identities[0],)])  # Nothing is appended for a skipped hypothesis.
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
