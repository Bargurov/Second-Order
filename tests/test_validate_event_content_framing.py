"""Z1A — validate_event_content_framing: banned-framing gate for candidates.

Proves the validator REJECTS buy/sell/long/short/alpha/signal/trade/live trading/
proof/proves/confirmed framing and recommendation language in candidate PROSE,
ACCEPTS clean prose, and does NOT false-positive on banned substrings that appear
only inside source URLs / tickers / ids (e.g. ustr.gov/trade-agreements).
"""
import os
import sys
import tempfile
import unittest

import yaml

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import scripts.validate_event_content_framing as F  # noqa: E402


def _clean() -> dict:
    return {
        "id": "bis-chip-controls-2022-10-07",
        "event_date": "2022-10-07",
        "title": "Commerce export-control rule restricts advanced-node chip equipment to China",
        "source_url": "https://www.bis.doc.gov/index.php/documents/about-bis/newsroom/press-releases",
        "source_type": "regulator",
        "category": "export_controls",
        "mechanism_family": "sanction",
        "mechanism_summary": ("The rule gates US toolmakers from selling advanced-node equipment; "
                              "domestic equipment names face revenue exposure while the policy holds."),
        "affected_assets": [
            {"ticker": "SMH", "role": "exposed", "rationale": "semiconductor basket exposed to the restriction"},
        ],
        "benchmark": "SPY",
        "placebo_feasibility_guess": "likely_good",
        "limitation_or_falsifier": "descriptive event-window read at n = 1; not an established result.",
        "review_status": "candidate_only_not_ingested",
    }


def _write(candidates: list) -> str:
    fd, path = tempfile.mkstemp(suffix=".yaml", prefix="cand_frame_")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump({"candidates": candidates}, fh, sort_keys=False, allow_unicode=True)
    return path


class TestContentFraming(unittest.TestCase):
    def setUp(self):
        self._paths = []

    def tearDown(self):
        for p in self._paths:
            try:
                os.remove(p)
            except OSError:
                pass

    def _problems(self, candidates):
        p = _write(candidates)
        self._paths.append(p)
        return F.scan_candidates(p)

    def test_accepts_clean_prose(self):
        self.assertEqual(self._problems([_clean()]), [])

    def test_rejects_banned_framing_words_in_prose(self):
        for field, text in [
            ("mechanism_summary", "this is a strong buy signal for the sector"),
            ("title", "Analysts confirm a long trade setup"),
            ("limitation_or_falsifier", "proof of alpha in the event window"),
        ]:
            c = _clean(); c[field] = text
            self.assertTrue(self._problems([c]), f"should reject banned framing in {field}")

    def test_rejects_recommendation_language(self):
        c = _clean(); c["mechanism_summary"] = "we recommend the name with a $200 price target"
        self.assertTrue(self._problems([c]))

    def test_does_not_flag_banned_substring_inside_source_url(self):
        # 'trade' appears only in the URL path — must NOT trip the prose scan
        c = _clean()
        c["source_url"] = "https://ustr.gov/about-us/policy-offices/press-office/trade-agreements/notice"
        self.assertEqual(self._problems([c]), [])

    def test_does_not_flag_banned_substring_inside_ticker_or_id(self):
        c = _clean()
        c["id"] = "longshore-port-labor-2024-10-01"  # 'long' substring in id
        c["affected_assets"] = [{"ticker": "DAL", "role": "exposed", "rationale": "logistics exposure"}]
        self.assertEqual(self._problems([c]), [])

    def test_cli_exit_code_reflects_framing(self):
        good = _write([_clean()]); self._paths.append(good)
        self.assertEqual(F.main([good]), 0)
        bad_c = _clean(); bad_c["title"] = "buy signal"
        bad = _write([bad_c]); self._paths.append(bad)
        self.assertNotEqual(F.main([bad]), 0)


if __name__ == "__main__":
    unittest.main()
