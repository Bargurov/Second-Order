"""Z1A — validate_no_synthetic_data: structural + anti-synthetic candidate gate.

Proves the validator REJECTS synthetic/demo/rehearsal candidates, missing/placeholder
source URLs, non-canonical mechanism_family, missing affected-asset roles, bad
review_status / source_type, and forward-dated events — and ACCEPTS a minimal,
real-shaped, primary-source-backed candidate. Read-only; operates on a YAML file.
"""
import os
import sys
import tempfile
import unittest

import yaml

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import scripts.validate_no_synthetic_data as V  # noqa: E402


def _valid() -> dict:
    return {
        "id": "doj-search-antitrust-2020-10-20",
        "event_date": "2020-10-20",
        "title": "US Department of Justice files an antitrust complaint against a search platform",
        "source_url": "https://www.justice.gov/opa/pr/justice-department-antitrust-action",
        "source_type": "court",
        "category": "antitrust_regulation",
        "mechanism_family": "regulation",
        "mechanism_summary": ("An antitrust complaint raises the regulatory-risk discount on the "
                              "named platform; peers with similar exposure may reprice."),
        "affected_assets": [
            {"ticker": "GOOGL", "role": "exposed", "rationale": "named defendant facing remedy risk"},
        ],
        "benchmark": "SPY",
        "placebo_feasibility_guess": "likely_good",
        "limitation_or_falsifier": ("descriptive event-window read at n = 1; a complaint is a "
                                    "hypothesis, not an established outcome."),
        "review_status": "candidate_only_not_ingested",
    }


def _write(candidates: list) -> str:
    fd, path = tempfile.mkstemp(suffix=".yaml", prefix="cand_")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump({"candidates": candidates}, fh, sort_keys=False, allow_unicode=True)
    return path


class TestValidateNoSyntheticData(unittest.TestCase):
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
        return V.validate_candidates(p)

    def test_accepts_minimal_valid_candidate(self):
        self.assertEqual(self._problems([_valid()]), [])

    def test_rejects_synthetic_demo_rehearsal_markers(self):
        for marker_field, marker in [
            ("title", "[DEMO] synthetic placeholder event"),
            ("mechanism_summary", "rehearsal showcase_seed_v1 fixture text"),
            ("limitation_or_falsifier", "TODO: lorem ipsum placeholder"),
        ]:
            c = _valid(); c[marker_field] = marker
            self.assertTrue(self._problems([c]), f"should reject synthetic marker in {marker_field}")

    def test_rejects_missing_or_placeholder_source_url(self):
        c = _valid(); del c["source_url"]
        self.assertTrue(self._problems([c]))
        c = _valid(); c["source_url"] = "TODO"
        self.assertTrue(self._problems([c]))
        c = _valid(); c["source_url"] = "https://example.com/foo"
        self.assertTrue(self._problems([c]))
        c = _valid(); c["source_url"] = "not-a-url"
        self.assertTrue(self._problems([c]))

    def test_rejects_non_canonical_mechanism_family(self):
        for bad in ("regulatory_risk", "export_control", "made_up"):
            c = _valid(); c["mechanism_family"] = bad
            self.assertTrue(self._problems([c]), f"should reject family {bad}")

    def test_accepts_each_canonical_family(self):
        for fam in ("regulation", "tariff", "sanction", "supply_shock", "policy_surprise",
                    "industrial_policy", "commodity_squeeze", "ceasefire_deescalation"):
            c = _valid(); c["mechanism_family"] = fam
            self.assertEqual(self._problems([c]), [], f"canonical family {fam} should pass")

    def test_rejects_missing_or_bad_affected_asset_roles(self):
        c = _valid(); c["affected_assets"] = []
        self.assertTrue(self._problems([c]))
        c = _valid(); c["affected_assets"] = [{"ticker": "GOOGL", "rationale": "x"}]  # no role
        self.assertTrue(self._problems([c]))
        c = _valid(); c["affected_assets"] = [{"ticker": "GOOGL", "role": "winner", "rationale": "x"}]  # bad role
        self.assertTrue(self._problems([c]))

    def test_rejects_bad_review_status(self):
        c = _valid(); c["review_status"] = "ingested"
        self.assertTrue(self._problems([c]))

    def test_rejects_bad_source_type(self):
        c = _valid(); c["source_type"] = "blog"
        self.assertTrue(self._problems([c]))

    def test_rejects_bad_placebo_guess(self):
        c = _valid(); c["placebo_feasibility_guess"] = "great"
        self.assertTrue(self._problems([c]))

    def test_rejects_forward_dated_event(self):
        c = _valid(); c["event_date"] = "2099-01-01"
        self.assertTrue(self._problems([c]))

    def test_rejects_missing_required_field(self):
        for field in ("event_date", "title", "mechanism_summary", "benchmark",
                      "limitation_or_falsifier", "category"):
            c = _valid(); del c[field]
            self.assertTrue(self._problems([c]), f"should reject missing {field}")

    def test_cli_exit_code_reflects_validity(self):
        good = _write([_valid()]); self._paths.append(good)
        self.assertEqual(V.main([good]), 0)
        bad_c = _valid(); bad_c["mechanism_family"] = "made_up"
        bad = _write([bad_c]); self._paths.append(bad)
        self.assertNotEqual(V.main([bad]), 0)


if __name__ == "__main__":
    unittest.main()
