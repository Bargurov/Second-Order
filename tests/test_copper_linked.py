"""Bagdad's 4 Nov 2026 statement read for the copper tools from the verified FCX research (copper_linked): the fixed
table matches the committed records, the block is all available or all withheld with one reason, a fault anywhere in
the FCX package only withholds it, and no source number is typed into the product code."""
from decimal import Decimal
import hashlib
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest import mock

import fcx_fakes
from second_order import company_research_view as crv, copper_linked as cl

ROOT = Path(__file__).resolve().parent.parent
VALUES = {"nr-bagdad-capex-estimate": Decimal("4.5"), "nr-bagdad-cu-increment": Decimal("225"),
          "nr-bagdad-breakeven-cu": Decimal("4.0"), "nr-bagdad-breakeven-mo": Decimal("20"),
          "nr-bagdad-construction-years": Decimal("3.5")}
REASONS = {"news-changed": "the Bagdad release of 4 November 2026", "news-missing": "the Bagdad release of 4 November 2026",
           "10q-changed": "the third-quarter 2026 Form 10-Q", "10q-missing": "the third-quarter 2026 Form 10-Q",
           "facts-missing": "(503)", "facts-broken": "(500)", "unit-changed": "nr-bagdad-cu-increment",
           "record-no-value": "(KeyError)", "inputs-list": "(AttributeError)",
           "record-missing": "nr-bagdad-construction-years is not as the copper tools expect (missing)",
           "page-changed": "nr-bagdad-cu-increment is not as the copper tools expect (page)",
           "display-mismatch": "nr-bagdad-capex-estimate is not as the copper tools expect (state)",
           "capacity-zero": "nr-bagdad-cu-increment is not as the copper tools expect (value)"}
PRODUCT_FILES = ("second_order/copper_linked.py", "second_order/copper_producers.py", "second_order/copper_tools_view.py",
                 "frontend/src/components/CopperProducers.tsx", "frontend/src/components/CopperBits.tsx",
                 "frontend/src/copperTools.ts", "frontend/src/copperActions.ts")
TYPED = (r"(?<![\w.])4\.5(?!\d)", r"(?<![\w-])225(?!\d)", r"4\.00", r"3\.5 ?years", r"mid-2030", r"\$20\b",
         r"4 Nov(ember)? 2026", r"13 Feb(ruary)? 2026")


def tree(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob("*")) if path.is_file()}


class Temp(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="second-order-copper-linked-"))
        self.addCleanup(shutil.rmtree, self.temp, True)


class Table(Temp):
    def test_the_table_matches_the_committed_research(self):
        """Default run, no private data: withheld records keep the fields the table checks."""
        empty = self.temp / "no-documents"
        empty.mkdir()
        _, records, quotes = crv.resolved(crv.RESEARCH_DIR, empty)
        self.assertEqual(cl.table_problems(records, quotes), [])

    def test_a_changed_unit_is_a_table_problem(self):
        _, records, quotes = crv.resolved(*fcx_fakes.synthetic_package(self.temp, "unit-changed"))
        problems = cl.table_problems(records, quotes)
        self.assertEqual(len(problems), 1)
        self.assertIn("nr-bagdad-cu-increment", problems[0])
        self.assertIn("unit", problems[0])


class Verified(Temp):
    def test_verified(self):
        block = cl.linked(*fcx_fakes.synthetic_package(self.temp))
        self.assertEqual((block["state"], block["problem"]), ("available", None))
        self.assertEqual(cl.linked_values(block), VALUES)
        records = block["records"]
        self.assertEqual(set(records), set(cl.FIGURES) | set(cl.PASSAGES))
        self.assertEqual(records["nr-bagdad-breakeven-cu"]["display"], "4.00")
        self.assertEqual({key: records["nr-bagdad-cu-increment"][key] for key in ("kind", "role", "unit", "approximate")},
                         {"kind": "figure", "role": "capacity", "unit": "mlb_per_year", "approximate": True})
        schedule = records["nr-p-schedule"]
        self.assertEqual((schedule["kind"], schedule["role"], schedule["value"]), ("passage", "start", None))
        self.assertIn("mid-2030", schedule["quote"])
        self.assertEqual(records["q3-p-bagdad-approval"]["source"], "10q-2026q3")
        self.assertEqual(block["sources"]["news-2026-11-04"]["date"], "2026-11-04")
        self.assertEqual((block["sources"]["news-2026-11-04"]["form"], block["sources"]["10q-2026q3"]["form"]),
                         ("news release", "10-Q"))
        self.assertEqual(set(block["sources"]), {"news-2026-11-04", "10q-2026q3"})


class Failures(Temp):
    def test_each_failure_withholds_everything_with_its_reason(self):
        for variant, reason in REASONS.items():
            with self.subTest(variant=variant):
                block = cl.linked(*fcx_fakes.synthetic_package(self.temp / variant, variant))
                self.assertEqual(block["state"], "withheld")
                self.assertIn(reason, block["problem"])
                self.assertTrue(block["problem"].startswith("Not shown: "))
                self.assertTrue(all(item["value"] is None and item["display"] is None and item["quote"] is None
                                    for item in block["records"].values()))
                self.assertEqual(set(block["records"]), set(cl.FIGURES) | set(cl.PASSAGES))
                self.assertEqual(cl.linked_values(block), {})

    def test_the_boundary_wraps_only_the_fcx_read(self):
        research, documents = fcx_fakes.synthetic_package(self.temp)
        for error in (ValueError, TypeError, AttributeError):
            with self.subTest(error=error.__name__), mock.patch.object(crv, "resolved", side_effect=error("x")):
                block = cl.linked(research, documents)
                self.assertEqual(block["state"], "withheld")
                self.assertIn(f"({error.__name__})", block["problem"])
                self.assertEqual(cl.linked_values(block), {})

    def test_an_unexpected_error_is_not_swallowed(self):
        research, documents = fcx_fakes.synthetic_package(self.temp)
        with mock.patch.object(crv, "resolved", side_effect=ZeroDivisionError("x")):
            with self.assertRaises(ZeroDivisionError):
                cl.linked(research, documents)


class NoTypedFigures(unittest.TestCase):
    def test_no_source_number_is_typed(self):
        for name in PRODUCT_FILES:
            text = (ROOT / name).read_text(encoding="utf-8")
            for pattern in TYPED:
                with self.subTest(file=name, pattern=pattern):
                    self.assertIsNone(re.search(pattern, text))


@unittest.skipUnless(all((crv.SOURCES_DIR / item["folder"] / item["name"]).is_file()
                         for item in crv.load_sources(crv.RESEARCH_DIR)),
                     "the retained FCX documents are not on this machine (data/ is private)")
class Retained(unittest.TestCase):
    def test_the_retained_documents_read_available_and_stay_unchanged(self):
        before = tree(crv.SOURCES_DIR)
        block = cl.linked(crv.RESEARCH_DIR, crv.SOURCES_DIR)
        self.assertEqual(block["state"], "available")
        self.assertEqual(cl.linked_values(block), VALUES)
        self.assertEqual(tree(crv.SOURCES_DIR), before)


if __name__ == "__main__":
    unittest.main()
