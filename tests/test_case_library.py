"""The case library: curated, retrospective editorial cases that are read, never scored.

The committed content is checked against its official sources' metadata; the loader refuses any file that breaks the
contract (and with it the whole library); the API only reads; and nothing in the library can reach research scores.
"""
import ast
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from second_order import case_library
from second_order.api import create_app
from second_order.case_library import LIBRARY_DIR, LibraryRefused, case_view, library_view, load_library
from second_order.demo import run_demo
from second_order.dossier import prepare

ROOT = Path(__file__).resolve().parent.parent
FED = "https://www.federalreserve.gov/newsevents/pressreleases/"
BLS = "https://www.bls.gov/news.release/archives/"
# The fixed selection: four consecutive releases per category, each with its official address and the publication
# time the release states (EST in January, EDT from March), in publication order within each category.
OFFICIAL = {
    "Monetary policy": [
        ("fomc-2025-01-29", f"{FED}monetary20250129a.htm", "2025-01-29T14:00:00-05:00"),
        ("fomc-2025-03-19", f"{FED}monetary20250319a.htm", "2025-03-19T14:00:00-04:00"),
        ("fomc-2025-05-07", f"{FED}monetary20250507a.htm", "2025-05-07T14:00:00-04:00"),
        ("fomc-2025-06-18", f"{FED}monetary20250618a.htm", "2025-06-18T14:00:00-04:00"),
    ],
    "Employment": [
        ("empsit-2025-04-04", f"{BLS}empsit_04042025.htm", "2025-04-04T08:30:00-04:00"),
        ("empsit-2025-05-02", f"{BLS}empsit_05022025.htm", "2025-05-02T08:30:00-04:00"),
        ("empsit-2025-06-06", f"{BLS}empsit_06062025.htm", "2025-06-06T08:30:00-04:00"),
        ("empsit-2025-07-03", f"{BLS}empsit_07032025.htm", "2025-07-03T08:30:00-04:00"),
    ],
    "Inflation": [
        ("cpi-2025-04-10", f"{BLS}cpi_04102025.htm", "2025-04-10T08:30:00-04:00"),
        ("cpi-2025-05-13", f"{BLS}cpi_05132025.htm", "2025-05-13T08:30:00-04:00"),
        ("cpi-2025-06-11", f"{BLS}cpi_06112025.htm", "2025-06-11T08:30:00-04:00"),
        ("cpi-2025-07-15", f"{BLS}cpi_07152025.htm", "2025-07-15T08:30:00-04:00"),
    ],
}


G17 = "https://www.federalreserve.gov/releases/g17/"
H8 = "https://www.federalreserve.gov/releases/h8/"
TIE = "https://www.eia.gov/todayinenergy/detail.php?id="
BIS = "https://www.bis.gov/press-release/"
# The sector selection: per source family, the last three releases or announcements published on or before
# 30 September 2026, each with its official address, its stated (date-only) publication date and its sectors.
SECTOR_OFFICIAL = {
    "Energy analysis": [
        ("eia-tie-2026-09-22", f"{TIE}68184", "2026-09-22", ["energy"]),
        ("eia-tie-2026-09-25", f"{TIE}68204", "2026-09-25", ["energy"]),
        ("eia-tie-2026-09-30", f"{TIE}68224", "2026-09-30", ["energy", "manufacturing-automotive"]),
    ],
    "Export controls": [
        ("bis-2026-02-12", f"{BIS}applied-materials-pay-252-million-penalty-bis-illegally-exporting-semiconductor-"
                           "manufacturing-equipment", "2026-02-12", ["technology-semiconductors"]),
        ("bis-2026-06-17", f"{BIS}robert-bosch-gmbh-bosch-pay-36-million-penalty-bis-violations-pertaining-shipments-"
                           "huawei", "2026-06-17", ["technology-semiconductors", "manufacturing-automotive"]),
        ("bis-2026-07-10", f"{BIS}department-commerce-eases-export-controls-uae", "2026-07-10",
         ["technology-semiconductors"]),
    ],
    "Industrial production": [
        ("g17-2026-07-17", f"{G17}20260717/", "2026-07-17", ["manufacturing-automotive", "energy", "mining-materials"]),
        ("g17-2026-08-18", f"{G17}20260818/", "2026-08-18",
         ["manufacturing-automotive", "technology-semiconductors", "mining-materials"]),
        ("g17-2026-09-18", f"{G17}20260918/", "2026-09-18", ["manufacturing-automotive", "energy", "mining-materials"]),
    ],
    "Bank balance sheets": [
        ("h8-2026-09-11", f"{H8}20260911/", "2026-09-11", ["banking-credit"]),
        ("h8-2026-09-18", f"{H8}20260918/", "2026-09-18", ["banking-credit"]),
        ("h8-2026-09-25", f"{H8}20260925/", "2026-09-25", ["banking-credit"]),
    ],
}
WTO = "https://www.wto.org/english/news_e/news26_e/"
# The WTO entries (case-library-0.3): each a retained WTO news item, dated by WTO's own news-feed listing (the pages state
# no publication date), with its entry kind and the SHA-256 and size of the private copy it was written from.
TRADE_OFFICIAL = [
    ("wto-2026-09-28", f"{WTO}envir_28sep26_501_e.htm", "2026-09-28", "proceedings",
     "4d4204d3dcb24ab768d79cdb3ab6a90a4853645c38100deb385e3b6a6cc64301", 24842),
    ("wto-2026-10-05", f"{WTO}gc_05oct26_508_e.htm", "2026-10-05", "proceedings",
     "953ae012c0317a36a5359274a7118cf2e23318131a023696180ee3fa8ec7c861", 30568),
    ("wto-2026-10-08", f"{WTO}stat_08oct26_510_e.htm", "2026-10-08", "forecast",
     "1e527398df2b4015c0fb801dc936af8350cee7915baa738fb07450ae2f233527", 26795),
]
MACRO_IDS = {case_id for rows in OFFICIAL.values() for case_id, _, _ in rows}
SECTOR_IDS = {case_id for rows in SECTOR_OFFICIAL.values() for case_id, _, _, _ in rows}
TRADE_IDS = {row[0] for row in TRADE_OFFICIAL}
# The twelve macro cases as committed before sectors existed: canonical-JSON SHA-256 of each file's content, so line
# endings in a checkout do not matter but any change to a field does.
MACRO_CONTENT = {
    "cpi-2025-04-10": "3bba7e5945301ea9e24fef60a8fa6b88174ca1a6dbd6f3ef453249fe8673f5a4",
    "cpi-2025-05-13": "8eaa5f92b6e69240bf33aa3f87604e34b9350ecf70543fb6f370bd8d89a0b095",
    "cpi-2025-06-11": "30b64e00735fee18dce8051eed44d8bd70b20f3ed399c6e14e932d2ecb22c60b",
    "cpi-2025-07-15": "34dda7a909572785c140cc673cde2ef398e61b724101c3b056933df53fd1f31c",
    "empsit-2025-04-04": "404eaa41c3b234066b7e40bf5e486165d22b221723e7f32676774ba9003283cb",
    "empsit-2025-05-02": "f21f88c10e02c2e5a40f5be4d9bf3bcd9e040997596db276660fa12d51f2a79f",
    "empsit-2025-06-06": "1191e38e73b0356c31853f175c34a17d2300e0f5b0b715524b39f2bf15004a9b",
    "empsit-2025-07-03": "28375e88ebfcbf1a0b2291ae162cc028a5a08486d173909f0739a844492947a3",
    "fomc-2025-01-29": "94a51ac7117f1209d7fb901b1b1df28968cfc32e01edcbeb04e666063089aeed",
    "fomc-2025-03-19": "ecea5943c0e88ded942b6f900a3f5086af85464780212a2dff10d156c8120750",
    "fomc-2025-05-07": "32fb28765c0277e7ac29056a851f60703603e843ccbe1ea799a09186d0fd08ed",
    "fomc-2025-06-18": "e05e67d10b948ce1280808eca24ec40204631b8a487f69a7f8c3c6b2735468b0",
}
# The twelve sector cases as committed before the WTO entries, pinned the same way.
SECTOR_CONTENT = {
    "bis-2026-02-12": "2c9a0c51fee5e510c2b7817d4128ed4140aee416182f2534e8063a3981bcc45d",
    "bis-2026-06-17": "c30c0e94bb12a750b675b30342f4e01c49bef759a199f99e0d3709e8613d7f73",
    "bis-2026-07-10": "8d4e6978824e7e44b29db227d28e2a0747865cd54af2a8792106eef835aa1546",
    "g17-2026-07-17": "25b12a0fb31bdb67e6e227da44b78f49a36392fcec00c43eef0ac0d390017633",
    "g17-2026-08-18": "4d6dd687eefc7941828ba5006255f3f61aa645d92f7945b5e960396445bc0313",
    "g17-2026-09-18": "805f5bb3ba4e3be721fb5eea286c28da1d79f31bc99dfbfff71b232cc443237a",
    "h8-2026-09-11": "00ead2d05deff34fd63a29625970ce423b07098af28b7f43f9ba8737bd317058",
    "h8-2026-09-18": "ff943cfdca2e56a25c2b466373c4522a64054530ee1421073ba031d0d8d33a9a",
    "h8-2026-09-25": "37ac7600a50ec62f9afedb5931b9cb5b9b513f45e068b3c2fce8b9ac148fec97",
    "eia-tie-2026-09-22": "324b29402d74e9d8719bcf28fdf2eff1dae80554b1b2aca8c0e39f6301e455d1",
    "eia-tie-2026-09-25": "9a6ba917706c50806dc3113dd7b5efda24007153c41c51bff6a2626502eecbbe",
    "eia-tie-2026-09-30": "c984b5ddf3e5bad2c974cf227d40643dd103b05dc6455e5168405b34a1915ebc",
}
# The three WTO entries as committed, pinned the same way.
TRADE_CONTENT = {
    "wto-2026-09-28": "979a15c5b4a325f1d32488ea3cb7825f44a1f1ecf45b99a323486595634bd8fa",
    "wto-2026-10-05": "b339c1089c59399aad185746dd036ce92ec3f0ec6b74b8d80dd065b763bcb428",
    "wto-2026-10-08": "8bc7eb7afee0a4122c71121f000ee44d7152f30fec8585a169b5577623ed7035",
}
# Mining & materials (14 October 2026) changed three G.17 cases by addition only: the sector at the end of their sector
# lists and this many items at the end of these sections. Removing them gives back the content in SECTOR_CONTENT.
MINING_APPENDED = {
    "g17-2026-07-17": {"key_facts": 1, "competing_explanations": 1, "assumptions": 1, "missing_information": 1},
    "g17-2026-08-18": {"key_facts": 2, "channels": 1, "competing_explanations": 1, "assumptions": 1,
                       "missing_information": 1},
    "g17-2026-09-18": {"key_facts": 1, "channels": 1, "competing_explanations": 1, "assumptions": 1,
                       "missing_information": 1},
}
# The three G.17 cases with those additions, pinned the same way.
MINING_CONTENT = {
    "g17-2026-07-17": "bfb1faeb94960f311b87b560dbf391265b9f10ffb27d7a34c56c83096cb370b8",
    "g17-2026-08-18": "f3b75a4f61e6467acf34f4122feb131473af05ba0ae98c1deb75a700e4d872b3",
    "g17-2026-09-18": "140038161aa766031bd5721d885eb022bbf21e6c1f709d433e633e3a68fb8330",
}
REFERENCE_MONTHS = {"g17-2026-07-17": "June", "g17-2026-08-18": "July", "g17-2026-09-18": "August"}
# The collection before Mining & materials, without its introduction (which now counts five sectors).
COLLECTION_BEFORE_MINING = "d4d8aab686be23c9ecb121675e22a6f6f6c097a22b5f8b0cbeb1f29ef444164d"


def canonical(content: dict) -> str:
    """SHA-256 of canonical JSON: line endings in a checkout do not matter, but any change to a field does."""
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


def without_mining(case: dict) -> dict:
    """A G.17 case as it was before Mining & materials: the sector and the appended items taken off the ends."""
    earlier = copy.deepcopy(case)
    earlier["sectors"] = [slug for slug in earlier["sectors"] if slug != "mining-materials"]
    for section, count in MINING_APPENDED[case["id"]].items():
        earlier[section] = earlier[section][:-count]
    return earlier


def every_file(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def write_library(root: Path, collection: dict, cases: list[dict]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "collection.json").write_text(json.dumps(collection), encoding="utf-8")
    for case in cases:
        (root / f"{case['id']}.json").write_text(json.dumps(case), encoding="utf-8")
    return root


class CommittedLibraryTests(unittest.TestCase):
    def test_twelve_macro_cases_are_four_consecutive_releases_per_category_from_their_official_sources(self):
        library = load_library()
        cases = {case["id"]: case for case in library["cases"]}
        self.assertEqual(len(library["cases"]), 27)
        self.assertEqual(set(cases), MACRO_IDS | SECTOR_IDS | TRADE_IDS)
        for category, rows in OFFICIAL.items():
            listed = [case["id"] for case in library["cases"] if case["category"] == category]
            self.assertEqual(listed, [case_id for case_id, _, _ in rows], category)  # In release order.
            for case_id, url, published in rows:
                with self.subTest(case_id):
                    source = cases[case_id]["source"]
                    self.assertEqual((source["url"], source["published_at"]), (url, published))
                    self.assertIn(url, cases[case_id]["provenance"]["sources_read"])
        selection = library["collection"]["selection"]
        self.assertIn("consecutive", selection)
        self.assertIn("not for", selection)  # Not chosen by later market outcomes.

    def test_the_twelve_macro_cases_are_unchanged(self):
        for case_id, digest in MACRO_CONTENT.items():
            with self.subTest(case_id):
                content = json.loads((LIBRARY_DIR / f"{case_id}.json").read_text(encoding="utf-8"))
                canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                self.assertEqual(hashlib.sha256(canonical.encode("utf-8")).hexdigest(), digest)
                self.assertEqual(content["library_version"], "case-library-0.1")
        library = load_library()  # Market context is still declared for exactly the twelve, in publication order.
        self.assertEqual(library["collection"]["market_context"],
                         [case["id"] for case in library["cases"] if case["id"] in MACRO_IDS])

    def test_the_twelve_sector_cases_are_unchanged_but_for_the_mining_and_materials_additions(self):
        for case_id, digest in SECTOR_CONTENT.items():
            with self.subTest(case_id):
                content = json.loads((LIBRARY_DIR / f"{case_id}.json").read_text(encoding="utf-8"))
                self.assertEqual(content["library_version"], "case-library-0.2")
                if case_id in MINING_APPENDED:  # Nothing moved or changed: taking the additions off restores it.
                    self.assertEqual(canonical(content), MINING_CONTENT[case_id])
                    self.assertEqual(content["sectors"][-1], "mining-materials")
                    self.assertNotIn("mining-materials", content["sectors"][:-1])
                    content = without_mining(content)
                self.assertEqual(canonical(content), digest)

    def test_the_wto_entries_are_unchanged(self):
        for case_id, digest in TRADE_CONTENT.items():
            with self.subTest(case_id):
                self.assertEqual(canonical(json.loads((LIBRARY_DIR / f"{case_id}.json").read_text(encoding="utf-8"))),
                                 digest)

    def test_the_collection_gains_one_sector_and_only_its_introduction_changes(self):
        collection = json.loads((LIBRARY_DIR / "collection.json").read_text(encoding="utf-8"))
        earlier = {key: value for key, value in collection.items() if key != "introduction"}
        self.assertEqual(earlier["sectors"][-1]["slug"], "mining-materials")
        earlier["sectors"] = earlier["sectors"][:-1]
        self.assertEqual(canonical(earlier), COLLECTION_BEFORE_MINING)  # Labels, rules, cases and order as they were.
        introduction = collection["introduction"]
        self.assertTrue(introduction.startswith("Twenty-seven official releases and news items"))
        self.assertIn("five sectors", introduction)
        self.assertNotIn("four sectors", introduction)

    def test_mining_and_materials_lists_the_three_g17_releases_under_the_membership_rule(self):
        library = load_library()
        declared = {item["slug"]: item for item in library["sectors"]}
        self.assertIn("mining-materials", declared)
        sector = declared["mining-materials"]
        self.assertEqual(sector["label"], "Mining & materials")
        listed = [case for case in library["cases"] if "mining-materials" in case.get("sectors", [])]
        # The G.17 selection already in the library, listed again under one more sector: no new release or record.
        self.assertEqual([case["id"] for case in listed], list(MINING_APPENDED))
        self.assertIn("NAICS", sector["coverage"])  # Mining as G.17 defines it, not metal mines alone.
        for absent in ("prices", "companies", "returns"):  # Stated as not covered.
            self.assertIn(absent, sector["coverage"])
        self.assertIn("Manufacturing & automotive", sector["selection"])
        topical = re.compile(r"\b(mining|materials)\b", re.IGNORECASE)
        for case in listed:
            with self.subTest(case["id"]):
                facts = [f"{fact['label']} {fact['value']} {fact['basis']}" for fact in case["key_facts"]]
                channels = [f"{channel['title']} {channel['source_fact']}" for channel in case["channels"]]
                self.assertTrue(any(topical.search(text) for text in facts))
                self.assertTrue(any(topical.search(text) for text in channels))
                appended = case["key_facts"][-MINING_APPENDED[case["id"]]["key_facts"]:]
                for fact in appended:  # Reference month, seasonal adjustment and first-estimate status are shown.
                    self.assertTrue(fact["label"].endswith(REFERENCE_MONTHS[case["id"]]), fact["label"])
                    self.assertIn("seasonally adjusted", fact["basis"])
                    self.assertIn("preliminary", fact["basis"])

    def test_three_wto_entries_read_retained_news_items_dated_by_wtos_own_listing(self):
        library = load_library()
        cases = {case["id"]: case for case in library["cases"]}
        self.assertEqual([case["id"] for case in library["cases"] if case["category"] == "International trade"],
                         [row[0] for row in TRADE_OFFICIAL])
        for case_id, url, listed, kind, digest, size in TRADE_OFFICIAL:
            with self.subTest(case_id):
                case, source = cases[case_id], cases[case_id]["source"]
                self.assertEqual((case["library_version"], case["entry_kind"], case["sectors"], source["url"],
                                  source["published_at"], source["published_precision"]),
                                 ("case-library-0.3", kind, [], url, listed, "date"))
                self.assertEqual((source["retained"]["approval_id"], source["retained"]["sha256"],
                                  source["retained"]["bytes"]), ("wto-trade-sources-01", digest, size))
                self.assertIn("listing date", source["date_basis"])
                self.assertIn("placeholder", source["timezone_note"])  # The feed's midnight is not a time.
                self.assertEqual(case["provenance"]["sources_read"], [url])
                self.assertEqual(len(case["channels"]) == 0, kind == "proceedings")
                self.assertNotIn(case_id, library["collection"]["market_context"])

    def test_twelve_sector_cases_are_the_last_three_of_each_family_by_30_september_2026(self):
        library = load_library()
        cases = {case["id"]: case for case in library["cases"]}
        for category, rows in SECTOR_OFFICIAL.items():
            listed = [case["id"] for case in library["cases"] if case["category"] == category]
            self.assertEqual(listed, [case_id for case_id, _, _, _ in rows], category)  # In publication order.
            for case_id, url, published, sectors in rows:
                with self.subTest(case_id):
                    case = cases[case_id]
                    source = case["source"]
                    self.assertEqual((case["library_version"], source["url"], source["published_at"],
                                      source["published_precision"], case["sectors"]),
                                     ("case-library-0.2", url, published, "date", sectors))
                    self.assertLessEqual(published, "2026-09-30")
                    self.assertIn(url, case["provenance"]["sources_read"])
                    self.assertIn("date only", source["timezone_note"])  # No time or offset is invented.
                    self.assertNotIn("T", source["published_at"])
        declared = {sector["slug"]: sector for sector in library["sectors"]}
        self.assertEqual(list(declared), ["energy", "technology-semiconductors", "manufacturing-automotive",
                                          "banking-credit", "mining-materials"])
        for slug, sector in declared.items():
            with self.subTest(slug):
                self.assertIn("on or before 30 September 2026", sector["selection"])
                self.assertGreaterEqual(sum(slug in case.get("sectors", []) for case in library["cases"]), 3)
        self.assertIn("not for any later market outcome", library["collection"]["selection"])
        self.assertIn("stored once", library["collection"]["sector_membership"])

    def test_sector_membership_is_additive_and_no_record_is_duplicated(self):
        files = sorted(path.stem for path in LIBRARY_DIR.glob("*.json") if path.name != "collection.json")
        library = load_library()
        self.assertEqual(files, sorted(library["collection"]["cases"]))
        self.assertEqual(len(files), len(set(files)))
        multi = {case["id"]: case["sectors"] for case in library["cases"] if len(case.get("sectors", [])) > 1}
        self.assertEqual(set(multi), {"bis-2026-06-17", "g17-2026-07-17", "g17-2026-08-18", "g17-2026-09-18",
                                      "eia-tie-2026-09-30"})
        for case in library["cases"]:  # Macro cases and the WTO entries belong to no sector.
            self.assertEqual(case.get("sectors", []) == [], case["id"] in MACRO_IDS | TRADE_IDS, case["id"])
        counts = {sector["slug"]: sum(sector["slug"] in case.get("sectors", []) for case in library["cases"])
                  for sector in library["sectors"]}
        self.assertEqual(counts, {"energy": 5, "technology-semiconductors": 4, "manufacturing-automotive": 5,
                                  "banking-credit": 3, "mining-materials": 3})
        rows = [row["id"] for row in library_view()["cases"]]  # One row per case, however many sectors it is under.
        self.assertEqual(len(rows), 27)
        self.assertEqual(len(rows), len(set(rows)))
        titles = [case["title"] for case in library["cases"]]
        self.assertEqual(len(titles), len(set(titles)))
        # Sector cases attach no Treasury yields: market context stays with the twelve macro cases.
        self.assertTrue(set(library["collection"]["market_context"]) <= MACRO_IDS)

    def test_the_collection_is_in_publication_order_and_its_texts_are_distinct(self):
        library = load_library()
        keys = [case_library.order_key(case) for case in library["cases"]]
        self.assertEqual(keys, sorted(keys))
        timed = [datetime.fromisoformat(case["source"]["published_at"]) for case in library["cases"]
                 if case_library.precision(case["source"]) == "time"]
        self.assertEqual(timed, sorted(timed))
        for field in ("title", "summary"):
            self.assertEqual(len({case[field] for case in library["cases"]}), 27, field)
        paragraphs = [text for case in library["cases"] for text in case["overview"]]
        self.assertEqual(len(paragraphs), len(set(paragraphs)))  # No overview paragraph is reused.
        critiques = [point["detail"] for case in library["cases"] for point in case["critique"]]
        self.assertEqual(len(critiques), len(set(critiques)))

    def test_every_case_is_labelled_as_unreviewed_ai_assisted_retrospective_editorial_work(self):
        collection = load_library()["collection"]
        self.assertIn("AI-assisted", " ".join(collection["labels"]))
        for case in load_library()["cases"]:
            with self.subTest(case["id"]):
                provenance = case["provenance"]
                self.assertEqual((provenance["ai_assisted"], provenance["retrospective"],
                                  provenance["prepared_after_publication"], provenance["human_review"],
                                  provenance["research_use"]), (True, True, True, "not_reviewed", "excluded"))
                self.assertIsNone(case["expectations_benchmark"])  # No surprise is claimed without a benchmark.
                self.assertGreater(provenance["prepared_on"], case["source"]["published_at"][:10])

    def test_cases_are_editorial_content_not_hypotheses(self):
        hypothesis_fields = {"legs", "nodes", "edges", "frozen_at", "replay_as_of", "evidence_class", "usage",
                             "engine", "verdict", "evaluation", "observable_id", "story_id"}

        def keys(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    yield key
                    yield from keys(item)
            elif isinstance(value, list):
                for item in value:
                    yield from keys(item)

        for path in sorted(LIBRARY_DIR.glob("*.json")):
            with self.subTest(path.name):
                self.assertEqual(set(keys(json.loads(path.read_text(encoding="utf-8")))) & hypothesis_fields, set())


class LoaderTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "library"
        committed = load_library()
        self.collection = json.loads((LIBRARY_DIR / "collection.json").read_text(encoding="utf-8"))
        self.cases = [copy.deepcopy(case) for case in committed["cases"]]

    def refused(self, collection: dict | None = None, cases: list[dict] | None = None) -> str:
        """Write a library to a fresh folder (so no earlier file lingers) and return why it was refused."""
        self.tries = getattr(self, "tries", 0) + 1
        root = write_library(self.root.parent / f"library-{self.tries}", collection or self.collection,
                             self.cases if cases is None else cases)
        with self.assertRaises(LibraryRefused) as caught:
            load_library(root)
        return str(caught.exception)

    def changed(self, edit) -> list[dict]:
        cases = copy.deepcopy(self.cases)
        edit(cases[0])
        return cases

    def test_a_valid_copy_loads(self):
        write_library(self.root, self.collection, self.cases)
        self.assertEqual([case["id"] for case in load_library(self.root)["cases"]], self.collection["cases"])

    def test_a_case_that_breaks_the_contract_refuses_the_whole_library(self):
        edits = {
            "a hypothesis field": lambda case: case.update(verdict="supported"),
            "a missing section": lambda case: case.pop("critique"),
            "an empty section": lambda case: case.update(competing_explanations=[]),
            "too little critique": lambda case: case.update(critique=case["critique"][:1]),
            "a time without its offset": lambda case: case["source"].update(published_at="2025-03-19T14:00:00"),
            "a UTC 'Z' instead of an offset": lambda case: case["source"].update(published_at="2025-03-19T18:00:00Z"),
            "an unofficial source": lambda case: case["source"].update(url="https://example.com/fomc.htm"),
            "a plain-http source": lambda case: case["source"].update(url=case["source"]["url"].replace("https", "http")),
            "a claimed human review": lambda case: case["provenance"].update(human_review="human_reviewed"),
            "research use": lambda case: case["provenance"].update(research_use="research"),
            "not AI-assisted": lambda case: case["provenance"].update(ai_assisted=False),
            "an expectations benchmark": lambda case: case.update(expectations_benchmark="consensus +0.2%"),
            "prepared before publication": lambda case: case["provenance"].update(prepared_on="2025-01-01"),
            "a fact without its basis": lambda case: case["key_facts"][0].pop("basis"),
            "a channel without its interpretation": lambda case: case["channels"][0].update(interpretation=""),
            "padded text": lambda case: case.update(summary=f" {case['summary']}"),
            "a source not listed as read": lambda case: case["provenance"].update(sources_read=[]),
            "sectors on a 0.1 case": lambda case: case.update(sectors=["energy"]),
            "a query on an official address": lambda case: case["source"].update(url=case["source"]["url"] + "?x=1"),
        }
        for name, edit in edits.items():
            with self.subTest(name):
                self.refused(cases=self.changed(edit))

    def test_a_wto_entry_that_breaks_the_contract_refuses_the_whole_library(self):
        position = {case["id"]: number for number, case in enumerate(self.cases)}

        def changed(case_id: str, edit) -> list[dict]:
            cases = copy.deepcopy(self.cases)
            edit(cases[position[case_id]])
            return cases

        edits = {
            "a forecast without channels": ("wto-2026-10-08", lambda case: case.update(channels=[])),
            "an unknown entry kind": ("wto-2026-10-08", lambda case: case.update(entry_kind="speech")),
            "no date basis": ("wto-2026-09-28", lambda case: case["source"].pop("date_basis")),
            "a retained copy from another approval": ("wto-2026-09-28", lambda case: case["source"]["retained"].update(
                approval_id="another-approval")),
            "a malformed retained hash": ("wto-2026-10-05", lambda case: case["source"]["retained"].update(sha256="x")),
            "a retrieval time without an offset": ("wto-2026-10-05", lambda case: case["source"]["retained"].update(
                retrieved_at="2026-10-12T12:25:51")),
            "an undeclared sector": ("wto-2026-10-05", lambda case: case.update(sectors=["trade"])),
            "a claimed human review": ("wto-2026-10-08", lambda case: case["provenance"].update(
                human_review="human_reviewed")),
        }
        for name, (case_id, edit) in edits.items():
            with self.subTest(name):
                self.refused(cases=changed(case_id, edit))
        wto_on_sector_case = changed("h8-2026-09-11", lambda case: case["source"].update(
            url="https://www.wto.org/english/news_e/news26_e/gc_05oct26_508_e.htm"))
        self.assertIn("expected an https address", self.refused(cases=wto_on_sector_case))
        older = {**self.collection, "library_version": "case-library-0.2"}
        self.assertIn("lists no case of a later version", self.refused(collection=older))
        root = write_library(self.root.parent / "proceedings-with-channels", self.collection, changed(
            "wto-2026-09-28", lambda case: case.update(channels=copy.deepcopy(self.cases[position["wto-2026-10-08"]]
                                                                             ["channels"]))))
        self.assertEqual(len(load_library(root)["cases"]), 27)  # Channels are optional for proceedings, not banned.

    def test_a_sector_case_that_breaks_the_contract_refuses_the_whole_library(self):
        index = next(number for number, case in enumerate(self.cases) if case["id"] == "h8-2026-09-11")

        def changed(edit) -> list[dict]:
            cases = copy.deepcopy(self.cases)
            edit(cases[index])
            return cases

        edits = {
            "an undeclared sector": lambda case: case.update(sectors=["astrology"]),
            "a repeated sector": lambda case: case.update(sectors=["banking-credit", "banking-credit"]),
            "no sector": lambda case: case.update(sectors=[]),
            "a time on a date-only source": lambda case: case["source"].update(published_at="2026-09-11T16:15:00-04:00"),
            "an unknown precision": lambda case: case["source"].update(published_precision="hour"),
            "no precision": lambda case: case["source"].pop("published_precision"),
            "an impossible date": lambda case: case["source"].update(published_at="2026-09-31"),
            "a claimed human review": lambda case: case["provenance"].update(human_review="human_reviewed"),
            "another EIA query": lambda case: case["source"].update(
                url="https://www.eia.gov/todayinenergy/detail.php?id=1&x=2"),
            "an unofficial host": lambda case: case["source"].update(url="https://www.example.com/h8.htm"),
        }
        for name, edit in edits.items():
            with self.subTest(name):
                self.refused(cases=changed(edit))
        collection = copy.deepcopy(self.collection)
        collection["sectors"].append(dict(collection["sectors"][0]))
        self.assertIn("distinct slugs", self.refused(collection=collection))
        undeclared = {**self.collection, "sectors": [sector for sector in self.collection["sectors"]
                                                     if sector["slug"] != "mining-materials"]}
        self.assertIn("mining-materials", json.dumps(self.collection["sectors"]))  # Declared, so it can be taken away.
        self.assertIn("expected distinct sectors the collection declares", self.refused(collection=undeclared))
        dated = {**self.collection, "market_context": self.collection["market_context"] + ["h8-2026-09-11"]}
        self.assertIn("publication time", self.refused(collection=dated))
        old = {key: value for key, value in self.collection.items() if key not in ("sectors", "sector_membership")}
        self.assertIn("lists no case of a later version",
                      self.refused(collection={**old, "library_version": "case-library-0.1"}))

    def test_a_file_that_is_not_an_object_is_refused_not_crashed(self):
        old = {key: value for key, value in self.collection.items() if key not in ("sectors", "sector_membership")}
        macro = [case for case in self.cases if case["id"] in MACRO_IDS]
        layouts = {"the collection": ({**self.collection}, self.cases, "collection"),
                   "a case": ({**self.collection}, self.cases, "h8-2026-09-11"),
                   "a case in a 0.1 collection": ({**old, "library_version": "case-library-0.1",
                                                   "cases": [case["id"] for case in macro]}, macro, "cpi-2025-04-10")}
        for number, (name, (collection, cases, broken)) in enumerate(layouts.items()):
            with self.subTest(name):
                root = write_library(self.root.parent / f"array-{number}", collection, cases)
                (root / f"{broken}.json").write_text("[]", encoding="utf-8")
                with self.assertRaises(LibraryRefused):
                    load_library(root)

    def test_files_and_the_collection_must_agree(self):
        swapped = list(self.collection["cases"])
        swapped[0], swapped[1] = swapped[1], swapped[0]
        self.assertIn("publication order", self.refused(collection={**self.collection, "cases": swapped}))
        self.assertIn("listed", self.refused(cases=self.cases[:2]))
        renamed = self.changed(lambda case: case.update(id="another-case"))
        self.assertIn("another-case", self.refused(cases=renamed))
        self.refused(collection={**self.collection, "cases": self.collection["cases"] + ["missing-case"]})
        self.refused(collection={**self.collection, "library_version": "case-library-0.0"})
        self.refused(collection={**self.collection, "market_context": ["no-such-case"]})
        self.refused(collection={**self.collection, "market_context": "fomc-2025-03-19"})
        write_library(self.root, self.collection, self.cases)
        (self.root / "stray.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(LibraryRefused) as caught:
            load_library(self.root)
        self.assertIn("stray", str(caught.exception))

    def test_strict_json_refuses_repeated_keys(self):
        write_library(self.root, self.collection, self.cases)
        path = self.root / f"{self.cases[0]['id']}.json"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace('"title":', '"title": "first", "title":', 1), encoding="utf-8")
        with self.assertRaises(LibraryRefused):
            load_library(self.root)

    def test_views_list_cases_in_order_with_neighbours(self):
        index = library_view()
        self.assertEqual(index["view_version"], case_library.VIEW_VERSION)
        ids = [row["id"] for row in index["cases"]]
        self.assertEqual(ids, self.collection["cases"])
        self.assertEqual(set(index["cases"][0]), {"id", "title", "category", "summary", "published_at",
                                                  "published_as_stated", "publication", "publisher", "sectors",
                                                  "market_context"})
        self.assertEqual([row["id"] for row in index["cases"] if row["market_context"]],
                         [case_id for case_id in ids if case_id in MACRO_IDS])  # Every macro case, no sector case.
        self.assertEqual([sector["slug"] for sector in index["sectors"]],
                         ["energy", "technology-semiconductors", "manufacturing-automotive", "banking-credit",
                          "mining-materials"])
        rows = {row["id"]: row for row in index["cases"]}
        self.assertEqual(rows["fomc-2025-01-29"]["publication"],
                         {"precision": "time", "date": "2025-01-29", "at": "2025-01-29T14:00:00-05:00"})
        self.assertEqual((rows["fomc-2025-01-29"]["sectors"], rows["g17-2026-09-18"]["sectors"]),
                         ([], ["manufacturing-automotive", "energy", "mining-materials"]))
        self.assertEqual(case_view("g17-2026-08-18")["sectors"],
                         [{"slug": "manufacturing-automotive", "label": "Manufacturing & automotive"},
                          {"slug": "technology-semiconductors", "label": "Technology & semiconductors"},
                          {"slug": "mining-materials", "label": "Mining & materials"}])
        self.assertEqual(rows["h8-2026-09-25"]["publication"],
                         {"precision": "date", "date": "2026-09-25", "at": "2026-09-25"})
        self.assertTrue(case_view(ids[0])["market_context"])
        sector_case = case_view("eia-tie-2026-09-30")
        self.assertEqual((sector_case["market_context"], sector_case["sectors"], sector_case["publication"]["precision"]),
                         (False, [{"slug": "energy", "label": "Energy"},
                                  {"slug": "manufacturing-automotive", "label": "Manufacturing & automotive"}], "date"))
        first, last = case_view(ids[0]), case_view(ids[-1])
        self.assertEqual((first["position"], first["count"], first["previous"], first["next"]["id"]),
                         (1, len(ids), None, ids[1]))
        self.assertEqual((last["previous"]["id"], last["next"]), (ids[-2], None))
        for unknown in ("not-a-case", "../collection", "FOMC-2025-03-19", ""):
            with self.subTest(unknown), self.assertRaises(LibraryRefused) as caught:
                case_view(unknown)
            self.assertEqual(caught.exception.status, 404)


class ApiTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        # No prepared Dossiers, drafts or runtime records: the library still works.
        self.client = TestClient(create_app(self.root / "prepared", None, self.root / "prepared-drafts",
                                            self.root / "reviews", self.root / "intake", self.root / "attempts"),
                                 base_url="http://127.0.0.1:8000")
        self.addCleanup(self.client.close)

    def test_the_library_is_served_read_only_without_any_runtime_records(self):
        before = every_file(LIBRARY_DIR)
        index = self.client.get("/api/case-library")
        self.assertEqual(index.status_code, 200)
        self.assertEqual(index.json(), library_view())
        for row in index.json()["cases"]:
            response = self.client.get(f"/api/case-library/{row['id']}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), case_view(row["id"]))
        self.assertEqual(self.client.get("/api/case-library/no-such-case").status_code, 404)
        self.assertEqual(self.client.get("/api/dossiers").status_code, 503)  # Unprepared, and the library is unaffected.
        for method in ("post", "put", "delete"):
            self.assertEqual(getattr(self.client, method)("/api/case-library").status_code, 405)
        self.assertEqual(every_file(LIBRARY_DIR), before)
        self.assertEqual(list(self.root.iterdir()), [])  # Nothing was written anywhere.

    def test_opening_and_reopening_the_library_makes_no_outside_call(self):
        blocked = AssertionError("a library read tried to open a network connection")
        before = every_file(LIBRARY_DIR)
        with patch("socket.create_connection", side_effect=blocked), patch("socket.getaddrinfo", side_effect=blocked):
            for _ in range(2):  # Opening, then reopening.
                index = self.client.get("/api/case-library").json()
                for row in index["cases"]:
                    self.assertEqual(self.client.get(f"/api/case-library/{row['id']}").status_code, 200)
                    status = self.client.get(f"/api/case-library/{row['id']}/market-context").status_code
                    self.assertEqual(status, 200 if row["market_context"] else 404, row["id"])
        self.assertEqual(every_file(LIBRARY_DIR), before)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_an_invalid_library_is_reported_and_never_partly_served(self):
        broken = self.root / "broken-library"
        collection = json.loads((LIBRARY_DIR / "collection.json").read_text(encoding="utf-8"))
        cases = [copy.deepcopy(case) for case in load_library()["cases"]]
        cases[1]["provenance"]["human_review"] = "human_reviewed"
        write_library(broken, collection, cases)
        client = TestClient(create_app(self.root / "prepared", None, library=broken), base_url="http://127.0.0.1:8000")
        self.addCleanup(client.close)
        self.assertEqual(client.get("/api/case-library").status_code, 500)
        self.assertEqual(client.get(f"/api/case-library/{cases[0]['id']}").status_code, 500)


class ResearchIsolationTests(unittest.TestCase):
    def test_the_library_module_depends_on_nothing_that_scores_or_stores(self):
        tree = ast.parse((ROOT / "second_order" / "case_library.py").read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                    for alias in node.names}
        imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                     if isinstance(node, ast.ImportFrom) and node.module and node.level == 0}
        relative = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level > 0]
        self.assertEqual(relative, [])  # No project module: not the store, scoring, evaluation or Dossiers.
        self.assertLessEqual(imported, {"json", "re", "datetime", "pathlib", "urllib"})

    def test_library_cases_never_enter_prepared_views_or_research_scoreboards(self):
        before = run_demo()["research_scoreboards"]
        load_library()
        library_view()
        self.assertEqual(run_demo()["research_scoreboards"], before)
        with tempfile.TemporaryDirectory() as folder:
            index = prepare(Path(folder) / "prepared")
        listed = json.dumps(index)
        for case in load_library()["cases"]:
            self.assertNotIn(case["id"], listed)
            self.assertNotIn(case["source"]["url"], listed)
        self.assertEqual({row["usage"] for row in index["dossiers"]}, {"showcase"})


if __name__ == "__main__":
    unittest.main()
