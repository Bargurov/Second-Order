"""The committed content whose bytes are fingerprinted is checked out with the same bytes on every platform.

Two kinds of committed content are bound by the SHA-256 of their bytes, not of their parsed JSON, so git's line-ending
conversion would change what they are bound to. ``.gitattributes`` fixes their line endings, for these paths only;
their committed blobs are unchanged (both are stored with LF), so nothing is rewritten:

- the case-library case files (an enrichment binds its case by ``case_file_sha256``; second_order/case_enrichments.py)
  are checked out with LF (``text eol=lf``), the bytes the two enrichments were bound to;
- the public news-relevance sets (an annotation reply must carry the set's ``set_sha256``;
  second_order/relevance_eval.py) are checked out with CRLF (``text eol=crlf``): the recorded measurement
  (reval-aee4287e36af90be for dev, kept write-once under the local newsroom folder) was measured on a Windows checkout
  and binds the CRLF bytes, so every checkout reads the sets as that measurement did. The private holdout has its own
  rule and its pin in tests/test_relevance_holdout_private.py.

Other content (theses, the copper catalogue, related cases) is fingerprinted as canonical JSON and is left as it is;
content/market-context keeps its own ``-text`` rule.
"""
import unittest
from pathlib import Path

from second_order import relevance_eval

ROOT = Path(__file__).resolve().parent.parent
CASES = "content/case-library/*.json"  # Top-level case files only; enrichments/ is parsed, not hashed.
SETS = "content/news-relevance/*.json"
RECORDED = {"dev": "884ebecfdb48f1e7100b99db4145550ab4ffefede5108e330f05fe22cc14059c"}


class LineEndingTest(unittest.TestCase):
    def test_gitattributes_fixes_the_line_endings_of_the_byte_bound_content_only(self):
        lines = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
        self.assertIn(f"/{CASES} text eol=lf", lines)
        self.assertIn(f"/{SETS} text eol=crlf", lines)

    def test_every_case_file_is_checked_out_with_lf_only(self):
        files = sorted(ROOT.glob(CASES))
        self.assertGreaterEqual(len(files), 28)  # 28 case-library files when written.
        with_cr = [path.relative_to(ROOT).as_posix() for path in files if b"\r" in path.read_bytes()]
        self.assertEqual(with_cr, [], "a case file was checked out with CR; see .gitattributes")

    def test_every_relevance_set_is_checked_out_with_crlf_line_ends(self):
        files = sorted(ROOT.glob(SETS))
        self.assertEqual([path.stem for path in files], ["dev", "sample"])
        for path in files:
            data = path.read_bytes()
            self.assertGreater(data.count(b"\r\n"), 0, path.name)
            self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), f"{path.name} has a line end without CR")

    def test_the_sets_read_as_the_recorded_measurement_read_them(self):
        for name, digest in RECORDED.items():
            self.assertEqual(relevance_eval.load(name)["set_sha256"], digest, name)


if __name__ == "__main__":
    unittest.main()
