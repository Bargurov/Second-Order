"""Prepared Dossier views: unchanged records, the scorer's own reference, offline preparation."""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from second_order.demo import SHOWCASE_AS_OF, load_market, load_provenance, load_showcases, run_demo
from second_order.dossier import VIEW_VERSION, build_dossier, prepare
from second_order.evaluation import evaluate, scoreboard
from second_order.scoring import Rules, percentile_rank


class DossierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.market, cls.provenance, cls.showcases = load_market(), load_provenance(), load_showcases()
        cls.views = [build_dossier(hypothesis, cls.market, cls.provenance) for hypothesis in cls.showcases]

    def test_preparation_does_not_change_the_records(self):
        for hypothesis, view in zip(self.showcases, self.views):
            self.assertEqual(view["evaluation"], evaluate(hypothesis, self.market, SHOWCASE_AS_OF))
            self.assertEqual(view["hypothesis"], hypothesis.model_dump(mode="json"))
            self.assertEqual(view["view_version"], VIEW_VERSION)

    def test_existing_verdicts_and_research_exclusion_hold(self):
        verdicts = {view["hypothesis"]["event"]["published_at"][:7]: view["evaluation"]["verdict"]
                    for view in self.views}
        self.assertEqual(verdicts, {"2024-06": "supported", "2024-10": "contradicted"})
        demo = {row["id"]: row["verdict"] for row in run_demo()["dossiers"]}
        self.assertEqual({view["id"]: view["evaluation"]["verdict"] for view in self.views}, demo)
        for view in self.views:
            self.assertFalse(view["research"]["enters_research_scores"])
            self.assertEqual(view["label"], "Manually reconstructed replay · showcase illustration")
        for kind in ("replay", "prospective"):
            evaluations = [view["evaluation"] for view in self.views]
            self.assertEqual(scoreboard(evaluations, kind, Rules().hash)["hypotheses"], 0)

    def test_reference_is_the_distribution_the_scorer_ranked(self):
        for view in self.views:
            results = {leg["leg_id"]: leg for leg in view["evaluation"]["legs"]}
            for leg in view["legs"]:
                result, reference = results[leg["leg_id"]], leg["reference"]
                with self.subTest(dossier=view["id"][:8], leg=leg["leg_id"]):
                    values = reference["values"]
                    self.assertEqual(len(values), result["reference_windows"])
                    self.assertEqual(percentile_rank(result["signed_move"], values), result["percentile_rank"])
                    self.assertEqual(reference["event_signed_move"], result["signed_move"])
                    self.assertEqual(reference["below"] + reference["equal"] + reference["above"], len(values))
                    self.assertEqual(sum(reference["histogram"]["counts"]), len(values))
                    edges = reference["histogram"]["edges"]
                    self.assertLessEqual(edges[0], min(values + [result["signed_move"]]))
                    self.assertGreaterEqual(edges[-1], max(values + [result["signed_move"]]))

    def test_mismatched_reference_fails_closed(self):
        from second_order.dossier import reference_view
        result = {"signed_move": 1.0, "percentile_rank": 0.5, "reference_windows": 3}
        with self.assertRaises(ValueError):
            reference_view((0.0, 2.0, 3.0), result)

    def test_chart_covers_publication_anchors_and_horizon_within_the_clock(self):
        for view in self.views:
            published = datetime.fromisoformat(view["hypothesis"]["event"]["published_at"])
            results = {leg["leg_id"]: leg for leg in view["evaluation"]["legs"]}
            for leg in view["legs"]:
                result, series = results[leg["leg_id"]], leg["series"]
                times = [timestamp for timestamp, _ in series["points"]]
                with self.subTest(dossier=view["id"][:8], leg=leg["leg_id"]):
                    for key in ("event_anchor", "score_anchor", "target_at", "reference_end"):
                        self.assertIn(result[key], times)
                    self.assertLess(datetime.fromisoformat(times[0]), published)
                    self.assertLessEqual(datetime.fromisoformat(times[-1]), SHOWCASE_AS_OF)
                    self.assertEqual(series["provenance"]["timestamp_basis"], "fictional_daily")
                    self.assertEqual(series["caption"].split(" · ")[0], "fictional-demo")
                    self.assertTrue(series["caption"].endswith("invented by demo-market-0.1"))

    def test_limitations_name_the_four_caveats(self):
        for view in self.views:
            self.assertEqual([item["title"] for item in view["limitations"]],
                             ["Fictional demonstration data", "Illustrative daily timestamps",
                              "Retrospective hypothesis", "No causal proof"])
            fictional = view["limitations"][0]["text"]
            self.assertTrue(fictional.startswith("FICTIONAL demonstration series: every number is invented"))
            self.assertIn("demo-market-0.1", fictional)

    def test_prepare_is_offline_deterministic_and_round_trips(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch("socket.socket.connect", side_effect=AssertionError("No network during preparation")):
            first, second = prepare(Path(folder) / "a"), prepare(Path(folder) / "b")
            self.assertEqual(first, second)
            self.assertEqual(len(first["dossiers"]), 2)
            for row in first["dossiers"]:
                raw = (Path(folder) / "a" / f"{row['id']}.json").read_bytes()
                self.assertEqual(raw, (Path(folder) / "b" / f"{row['id']}.json").read_bytes())
                view = json.loads(raw)
                for leg, result in zip(view["legs"], view["evaluation"]["legs"]):
                    self.assertEqual(percentile_rank(result["signed_move"], leg["reference"]["values"]),
                                     result["percentile_rank"])
            self.assertEqual(list(Path(folder).rglob("*.db*")), [])


if __name__ == "__main__":
    unittest.main()
