"""The SYNTHETIC FCX package (fcx_fakes): a temporary copy of the committed research package whose four documents are
made-up files, so default runs can read the FCX records as verified without the private retained documents."""
import hashlib
from pathlib import Path
import tempfile
import unittest

import fcx_fakes
from second_order import company_research_view as crv


def tree(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob("*")) if path.is_file() and "__pycache__" not in path.parts}


class SyntheticPackage(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="second-order-fcx-fakes-"))
        self.addCleanup(__import__("shutil").rmtree, self.temp, True)

    def test_verified_package_verifies(self):
        sources, records, _ = crv.resolved(*fcx_fakes.synthetic_package(self.temp))
        self.assertEqual({sid: item["state"] for sid, item in sources.items()},
                         {sid: "verified" for sid in crv.SOURCE_IDS})
        self.assertEqual(records["nr-bagdad-cu-increment"]["value"], "225")
        research, documents = self.temp / "research", self.temp / "sources"
        self.assertTrue(all(path.read_bytes().startswith(b"SYNTHETIC FCX document ")
                            for path in documents.rglob("*") if path.is_file()))
        self.assertTrue((research / "facts.json").is_file())

    def test_document_variants(self):
        for variant, sid, state in (("news-changed", "news-2026-11-04", "changed"),
                                    ("news-missing", "news-2026-11-04", "missing"),
                                    ("10q-changed", "10q-2026q3", "changed"),
                                    ("10q-missing", "10q-2026q3", "missing")):
            with self.subTest(variant=variant):
                sources, _, _ = crv.resolved(*fcx_fakes.synthetic_package(self.temp / variant, variant))
                self.assertEqual(sources[sid]["state"], state)
                others = {key: item["state"] for key, item in sources.items() if key != sid}
                self.assertEqual(set(others.values()), {"verified"})

    def test_package_variants_refuse(self):
        for variant, status in (("facts-missing", 503), ("facts-broken", 500)):
            with self.subTest(variant=variant):
                with self.assertRaises(crv.CompanyRefused) as raised:
                    crv.resolved(*fcx_fakes.synthetic_package(self.temp / variant, variant))
                self.assertEqual(raised.exception.status, status)
        # The owner's case: an unrelated record without a value breaks resolved() with a KeyError.
        with self.assertRaises(KeyError):
            crv.resolved(*fcx_fakes.synthetic_package(self.temp / "record-no-value", "record-no-value"))
        # An unrelated record whose inputs are a list breaks it with an AttributeError.
        with self.assertRaises(AttributeError):
            crv.resolved(*fcx_fakes.synthetic_package(self.temp / "inputs-list", "inputs-list"))

    def test_unit_changed_reads_but_differs(self):
        _, records, _ = crv.resolved(*fcx_fakes.synthetic_package(self.temp, "unit-changed"))
        self.assertEqual(records["nr-bagdad-cu-increment"]["unit"], "million pounds")

    def test_the_committed_research_is_untouched(self):
        before = tree(crv.RESEARCH_DIR)
        for variant in fcx_fakes.VARIANTS:
            fcx_fakes.synthetic_package(self.temp / variant, variant)
        self.assertEqual(tree(crv.RESEARCH_DIR), before)

    def test_an_unknown_variant_is_refused(self):
        with self.assertRaises(ValueError):
            fcx_fakes.synthetic_package(self.temp, "no-such-variant")


if __name__ == "__main__":
    unittest.main()
