"""Manufacturing breadth across the 19 NAICS subsectors, on SYNTHETIC G.17 pages that carry all 19 (g17_fakes), in
temporary folders: counts, majority boundaries, printed and negative zero, missing observations, the exact universe,
shifts within a release, revisions of the same month, persistence beside the industry findings, reuse, tampering and
concurrency. No network is reached and no retained local file is read.
"""
import json
import os
from pathlib import Path
import stat
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import g17_fakes
from g17_fakes import NONDURABLE, SCENARIO
from second_order import g17_breadth as breadth, g17_evidence as evidence, g17_insights
from test_g17 import BASE, CHECK, HEADERS, Harness, tree

PATHS = [f"{breadth.GROUP_PARENT[group]} / {label}" for group, rows in breadth.UNIVERSE.items() for label, _ in rows]
AGGREGATE = breadth.AGGREGATE


def month_values(release, month, aggregate, values):
    """Overrides setting the aggregate and the first len(values) subsectors (universe order) for one release-month;
    the remaining subsectors keep their small positive defaults."""
    out = {(release, AGGREGATE, month): aggregate}
    out.update({(release, path, month): value for path, value in zip(PATHS, values)})
    return out


def computed(harness, release, overrides, rows=g17_fakes.ROWS):
    page = g17_fakes.table1(release, overrides, rows)
    extract = harness.extract(release, overrides, **{"table1.htm": page})
    return extract, breadth.release_breadth(extract)


def month_of(result, key):
    return next(item for item in result["months"] if item["month"] == key)


class CountTests(Harness):
    def test_counts_shares_groups_and_members(self):
        values = ["-.2"] * 10 + [".0", "-.0"]
        _, result = computed(self, "20260918", month_values("20260918", "2026-04", ".3", values))
        april = month_of(result, "2026-04")
        self.assertEqual(april["counts"], {"positive": 7, "negative": 10, "printed_zero": 2, "missing": 0})
        self.assertEqual((april["expected"], april["state"], april["aggregate_vs_breadth"]), (19, "majority_down", True))
        self.assertEqual(april["shares"], {"positive": "7/19", "negative": "10/19", "printed_zero": "2/19"})
        self.assertEqual(april["groups"]["durable"], {"positive": 0, "negative": 10, "printed_zero": 1, "missing": 0,
                                                      "expected": 11})
        self.assertEqual(april["groups"]["nondurable"]["expected"], 8)
        self.assertIn({"label": "Machinery", "naics": "333", "group": "durable", "rate": "-.2"},
                      april["members"]["negative"])
        self.assertEqual({m["rate"] for m in april["members"]["printed_zero"]}, {".0", "-.0"})
        self.assertEqual(april["aggregate_rate"], ".3")
        self.assertEqual(breadth.share_text(10), "53%")

    def test_strict_majority_boundary_and_aggregate_direction(self):
        cases = {
            "nine down against a rise": (".3", ["-.2"] * 9 + [".0"], False, "no_majority"),
            "ten down against a rise": (".3", ["-.2"] * 10, True, "majority_down"),
            "an aggregate printed 0.0": (".0", ["-.2"] * 12, False, "majority_down"),
            "an aggregate printed -0.0": ("-.0", ["-.2"] * 12, False, "majority_down"),
            "ten up against a fall": ("-.2", [], True, "majority_up"),
            "nine up against a fall": ("-.2", ["-.1"] * 9 + [".0"], False, "no_majority"),
        }
        for name, (aggregate, values, met, state) in cases.items():
            with self.subTest(name):
                self.setUp()
                _, result = computed(self, "20260918", month_values("20260918", "2026-04", aggregate, values))
                april = month_of(result, "2026-04")
                self.assertEqual((april["aggregate_vs_breadth"], april["state"]), (met, state))
                self.assertEqual(any(f["type"] == "aggregate_vs_breadth" and f["month"] == "2026-04"
                                     for f in result["findings"]), met)

    def test_a_missing_observation_keeps_partial_counts_and_claims_nothing(self):
        values = ["-.2"] * 12 + [""]
        _, result = computed(self, "20260918", month_values("20260918", "2026-04", ".3", values))
        april = month_of(result, "2026-04")
        self.assertEqual(april["counts"], {"positive": 6, "negative": 12, "printed_zero": 0, "missing": 1})
        self.assertEqual((april["state"], april["shares"], april["aggregate_vs_breadth"]), ("incomplete", None, False))
        shifts = [s for s in result["shifts"] if "2026-04" in (s["from"], s["to"])]
        self.assertTrue(shifts and not any(s["compared"] or s["shift"] for s in shifts))
        self.assertFalse(any("2026-04" in (f.get("month"), f.get("to"), f.get("from")) for f in result["findings"]))


class UniverseTests(Harness):
    def test_the_universe_must_be_exactly_the_nineteen(self):
        extra = list(g17_fakes.ROWS)
        index = extra.index(next(row for row in extra if row[1][-1] == "Miscellaneous"))
        extra.insert(index + 1, ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Durable manufacturing",
                                                    "Extra products"), "999", "0.10"))
        moved = [row for row in g17_fakes.ROWS if row[1][-1] != "Machinery"]
        after = moved.index(next(row for row in moved if row[1][-1] == "Plastics and rubber products"))
        moved.insert(after + 1, ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Nondurable manufacturing",
                                                    "Machinery"), "333", "5.50"))
        recoded = [row if row[1][-1] != "Paper" or row[2] != "322" else (*row[:2], "3220", row[3])
                   for row in g17_fakes.ROWS]
        for name, rows, words in (("an extra subsector", extra, "not in the universe: Extra products"),
                                  ("a subsector under the other parent", moved, "nondurable: expected 8 subsectors, "
                                                                                "found 9"),
                                  ("a recoded subsector", recoded, "missing or different: Paper")):
            with self.subTest(name):
                self.setUp()
                _, result = computed(self, "20260918", SCENARIO, rows)
                self.assertEqual(result["state"], "unavailable")
                self.assertIn(words, result["detail"])
                self.assertEqual((result["months"], result["findings"]), ([], []))

    def test_a_duplicated_subsector_is_refused_with_the_whole_release(self):
        duplicate = list(g17_fakes.ROWS)
        index = duplicate.index(next(row for row in duplicate if row[1][-1] == "Machinery"))
        duplicate.insert(index + 1, duplicate[index])
        self.keep(pages={("20260918", "table1.htm"): g17_fakes.table1("20260918", SCENARIO, duplicate)})
        self.assertIn("repeats", self.check(409)["detail"])
        self.assertEqual(self.records(), {})

    def test_an_unavailable_breadth_does_not_stop_the_industry_findings(self):
        recoded = [row if row[1][-1] != "Chemicals" else (*row[:2], "3250", row[3]) for row in g17_fakes.ROWS]
        self.keep(pages={("20260918", "table1.htm"): g17_fakes.table1("20260918", SCENARIO, recoded)})
        reply = self.check()
        self.assertEqual((reply["release_results_created"], reply["breadth"]["release_results_created"]), (3, 3))
        listing = self.listing()
        self.assertEqual(listing["state"], "checked")
        self.assertIsNotNone(listing["divergence"])
        self.assertEqual(listing["breadth"]["latest"]["state"], "unavailable")
        self.assertIn("Chemicals", listing["breadth"]["latest"]["detail"])


class ComparisonTests(Harness):
    def test_shifts_stay_within_one_release(self):
        overrides = {**SCENARIO, **month_values("20260918", "2026-04", ".3", ["-.2"] * 10)}
        _, result = computed(self, "20260918", overrides)
        shift = next(s for s in result["shifts"] if s["to"] == "2026-04")
        self.assertEqual((shift["states"], shift["shift"]), (["majority_up", "majority_down"], True))
        self.assertEqual(shift["change"]["negative"], 10)
        self.assertIn({"type": "breadth_shift", "from": "2026-03", "to": "2026-04"}, result["findings"])

    def test_revisions_compare_the_same_month_and_show_switched_members(self):
        august = {("20260818", PATHS[0], "2026-06"): ".4", ("20260818", PATHS[1], "2026-06"): "-.3",
                  ("20260818", PATHS[2], "2026-06"): ".2"}
        september = {("20260918", PATHS[0], "2026-06"): "-.1", ("20260918", PATHS[1], "2026-06"): ".5",
                     ("20260918", PATHS[2], "2026-06"): ".0",
                     **month_values("20260918", "2026-04", ".3", ["-.2"] * 10)}
        overrides = {**SCENARIO, **august, **september}
        earlier, _ = computed(self, "20260818", overrides)
        later, _ = computed(self, "20260918", overrides)
        result = breadth.revision_breadth(earlier, later)
        self.assertEqual([m["month"] for m in result["months"]],
                         ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07"])
        june = next(m for m in result["months"] if m["month"] == "2026-06")
        self.assertEqual([r["label"] for r in june["reversals"]], ["Wood products", "Nonmetallic mineral products"])
        self.assertEqual([(z["label"], z["from"], z["to"]) for z in june["printed_zero_transitions"]],
                         [("Primary metals", "positive", "printed_zero")])
        self.assertEqual(june["change"], {"positive": -1, "negative": 0, "printed_zero": 1, "missing": 0})
        april = next(m for m in result["months"] if m["month"] == "2026-04")
        self.assertEqual((april["earlier"]["state"], april["later"]["state"], april["changed"]),
                         ("majority_up", "majority_down", True))
        self.assertEqual(len(april["reversals"]), 10)
        self.assertIn({"type": "breadth_revision", "month": "2026-04"}, result["findings"])
        with self.assertRaises(ValueError):
            breadth.revision_breadth(later, earlier)

    def test_unchanged_counts_with_switched_members_stay_visible(self):
        overrides = {**SCENARIO, ("20260818", PATHS[0], "2026-05"): "-.1", ("20260918", PATHS[1], "2026-05"): "-.1"}
        earlier, _ = computed(self, "20260818", overrides)
        later, _ = computed(self, "20260918", overrides)
        may = next(m for m in breadth.revision_breadth(earlier, later)["months"] if m["month"] == "2026-05")
        self.assertEqual((may["change"]["negative"], may["changed"], may["counts_unchanged_members_switched"]),
                         (0, False, True))
        self.assertEqual(len(may["reversals"]), 2)

    def test_changing_coverage_is_not_compared(self):
        overrides = {**SCENARIO, ("20260918", PATHS[3], "2026-05"): ""}
        earlier, _ = computed(self, "20260818", overrides)
        later, _ = computed(self, "20260918", overrides)
        may = next(m for m in breadth.revision_breadth(earlier, later)["months"] if m["month"] == "2026-05")
        self.assertEqual((may["compared"], may["changed"]), (False, False))
        self.assertEqual([c["label"] for c in may["coverage_changes"]], ["Fabricated metal products"])


class PersistenceTests(Harness):
    def scenario(self):
        self.keep(overrides={**SCENARIO, **month_values("20260918", "2026-04", ".3", ["-.2"] * 10)})

    def test_breadth_is_written_beside_the_industry_records_and_reused(self):
        self.scenario()
        reply = self.check()
        self.assertEqual(reply["breadth"]["release_results_created"], 3)
        self.assertEqual(reply["breadth"]["revision_results_created"], 2)
        self.assertTrue(reply["breadth"]["created"])
        written = self.records()
        self.assertEqual(sum(1 for name in written if name.startswith("breadth/")), 6)
        again = self.check(200)
        self.assertEqual((again["breadth"]["created"], again["breadth"]["release_results_created"]), (False, 0))
        self.assertEqual(self.records(), written)
        listing = self.listing()
        part = listing["breadth"]
        self.assertEqual((part["state"], part["latest"]["release"]), ("checked", "20260918"))
        self.assertEqual(part["universe"], {"expected": 19, "durable": 11, "nondurable": 8, "aggregate": AGGREGATE,
                                            "excluded": breadth.DEFINITIONS["excluded"]})
        april = next(m for m in part["latest"]["months"] if m["month"] == "2026-04")
        self.assertEqual((april["counts"]["negative"], april["shares"]["negative"]), (10, "53%"))
        kinds = [card["type"] for card in part["shown"]]
        self.assertEqual(kinds, sorted(kinds, key=lambda kind: ["aggregate_vs_breadth", "breadth_shift",
                                                                "breadth_revision"].index(kind)))
        self.assertIn("aggregate_vs_breadth", kinds)
        self.assertIn("breadth_revision", kinds)
        april_revision = next(card for card in part["shown"] if card["type"] == "breadth_revision"
                              and card["month"] == "2026-04")
        self.assertEqual(april_revision["condition"],
                         "In the September 18, 2026 release the aggregate stood against most subsectors: Manufacturing "
                         "(NAICS) +0.3% with 10 of 19 printed down; in the August 18, 2026 release it did not.")
        self.assertEqual(part["total"], sum(part["totals"].values()))
        tables = self.client.get("/api/insights/g17/tables").json()["breadth"]
        self.assertEqual([r["release"] for r in tables["releases"]], ["20260717", "20260818", "20260918"])
        self.assertEqual(len(tables["revisions"]), 2)
        self.assertEqual(self.records(), written)

    def test_an_earlier_industry_check_gets_breadth_only_from_the_next_explicit_check(self):
        self.scenario()
        with patch.object(g17_insights, "_breadth_check", lambda *args: {"check_id": "", "created": False,
                                                                         "release_results_created": 0,
                                                                         "revision_results_created": 0}):
            self.check()
        before = self.records()
        self.assertFalse(any(name.startswith("breadth/") for name in before))
        self.assertEqual(self.listing()["breadth"]["state"], "not_checked")
        self.assertEqual(self.records(), before)  # Reading computed and saved nothing.
        reply = self.check(201)
        self.assertEqual((reply["g17_check_created"], reply["extracts_created"], reply["release_results_created"],
                          reply["breadth"]["created"]), (False, 0, 0, True))
        after = self.records()
        self.assertTrue(all(after[name] == digest for name, digest in before.items()))
        self.assertTrue(all(name.startswith("breadth/") for name in set(after) - set(before)))

    def test_a_changed_selection_reuses_breadth_results(self):
        self.scenario()
        self.check()
        before = self.records()
        reply = self.check(201, json.dumps({"check_retained_g17": True, "releases": ["20260818", "20260918"]}))
        self.assertEqual((reply["breadth"]["release_results_created"], reply["breadth"]["revision_results_created"]),
                         (0, 0))
        self.assertTrue(all(self.records()[name] == digest for name, digest in before.items()))

    def tamper(self, kind, change):
        path = next((self.insights / "g17" / "breadth" / kind).glob("*.json"))
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        record = json.loads(path.read_text("utf-8"))
        change(record)
        path.write_text(json.dumps(record), encoding="utf-8")

    def test_breadth_records_that_do_not_verify_are_not_shown(self):
        for kind, change in (
                ("releases", lambda r: r["result"]["months"][0]["counts"].update(positive=0)),
                ("revisions", lambda r: r["result"]["months"][0].update(changed=True))):
            with self.subTest(kind):
                self.setUp()
                self.scenario()
                self.check()
                self.tamper(kind, change)
                listing = self.listing()
                self.assertEqual((listing["state"], listing["breadth"]["state"]), ("checked", "problem"))
                self.assertIsNotNone(listing["divergence"])  # The industry findings stay.

    def test_other_breadth_definitions_are_kept_but_not_shown(self):
        self.scenario()
        self.check()
        written = self.records()
        with patch.object(breadth, "DEFINITIONS_SHA256", "0" * 64):
            part = self.listing()["breadth"]
        self.assertEqual(part["state"], "problem")
        self.assertIn("other breadth definitions", part["detail"])
        self.assertEqual(self.records(), written)

    def test_concurrent_checks_create_each_breadth_record_once(self):
        self.scenario()
        replies = []

        def run():
            with TestClient(self.client.app, base_url=BASE) as client:
                replies.append(client.post("/api/insights/g17/checks", headers=HEADERS, content=CHECK).json())
        threads = [threading.Thread(target=run) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        folder = self.insights / "g17" / "breadth"
        self.assertEqual({kind: len(list((folder / kind).glob("*.json"))) for kind in ("releases", "revisions",
                                                                                       "checks")},
                         {"releases": 3, "revisions": 2, "checks": 1})
        self.assertEqual(sum(1 for reply in replies if reply["breadth"]["created"]), 1)
        self.assertEqual(len({reply["breadth"]["check_id"] for reply in replies}), 1)


if __name__ == "__main__":
    unittest.main()
